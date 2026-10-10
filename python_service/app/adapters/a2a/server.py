from __future__ import annotations

import asyncio
import base64
import logging
from datetime import timezone
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.server.routes.common import ServerCallContextBuilder
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import (
    ContentTypeNotSupportedError, ExtendedAgentCardNotConfiguredError, InvalidParamsError,
    PushNotificationNotSupportedError, TaskNotCancelableError, TaskNotFoundError, UnsupportedOperationError,
)
from google.protobuf.json_format import MessageToDict, ParseDict
from pydantic import ValidationError

from app.config import settings
from app.contracts.v1 import DiagnosticRequest
from app.services.diagnosis_service import DiagnosisService, ServiceError
from app.tasks.store import TaskStore

logger = logging.getLogger(__name__)


class ContextBuilder(ServerCallContextBuilder):
    def build(self, request):
        return ServerCallContext(state={"headers": dict(request.headers), "principal": request.state.principal})


def agent_card():
    base = settings.interop_public_url.rstrip("/")
    data = {
        "name": "SRP Error Analysis Agent", "description": "Execution-feedback diagnosis and retrieval decisions for code generation and repair agents.",
        "version": "1.0.0", "documentationUrl": base + "/docs",
        "supportedInterfaces": [{"url": base + "/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
        "skills": [{"id": operation, "name": operation, "description": description,
                    "tags": ["code", "diagnosis"], "inputModes": ["application/json"], "outputModes": ["application/json"]}
                   for operation, description in [
                       ("diagnose_error", "Diagnose structured external feedback without executing source."),
                       ("execute_and_diagnose", "Execute one Python/Java snippet against a nonempty STDIO suite and diagnose failures."),
                       ("check_syntax", "Check syntax/compilation only; does not establish test success.")]],
    }
    if settings.interop_api_token:
        data["securitySchemes"] = {"bearerAuth": {"httpAuthSecurityScheme": {"scheme": "bearer"}}}
        data["securityRequirements"] = [{"schemes": {"bearerAuth": {"list": []}}}]
    return ParseDict(data, pb.AgentCard())


def data_to_contract(value, model=DiagnosticRequest):
    # Protobuf Value represents all JSON numbers as doubles, including JSON integers.
    def integers(obj):
        if isinstance(obj, dict):
            return {k: integers(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [integers(v) for v in obj]
        if isinstance(obj, float) and obj.is_integer() and abs(obj) <= 2**53:
            return int(obj)
        return obj
    return model.model_validate(integers(MessageToDict(value)))


class DiagnosisHandler(RequestHandler):
    def __init__(self, service=None, store=None, workers=None, max_pending=None):
        self.service = service or DiagnosisService()
        self.store = store or TaskStore(settings.a2a_store_path)
        self.workers = workers or settings.a2a_workers
        self.max_pending = max_pending or settings.a2a_max_pending
        self.started = False
        self.jobs = {}

    async def start(self):
        self.store.open()
        for task in self.store.interrupted():
            self._status(task, pb.TASK_STATE_FAILED, "SERVICE_RESTARTED: interrupted work was not automatically replayed")
            self.store.save(task)
        self.executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="srp-a2a")
        self.slots = asyncio.Semaphore(self.workers)
        self.started = True

    async def close(self):
        self.started = False
        if self.jobs:
            await asyncio.gather(*self.jobs.values(), return_exceptions=True)
        self.executor.shutdown(wait=True)
        self.store.close()

    @staticmethod
    def _status(task, state, text=""):
        task.status.state = state
        task.status.timestamp.GetCurrentTime()
        task.status.ClearField("message")
        if text:
            task.status.message.CopyFrom(pb.Message(
                message_id=str(uuid4()), task_id=task.id, context_id=task.context_id,
                role=pb.ROLE_AGENT, parts=[pb.Part(text=text[:12000])]))

    @staticmethod
    def _owner(params, context):
        if params.tenant:
            raise UnsupportedOperationError("Multi-tenant routing is not enabled")
        return context.state["principal"]

    def _get(self, task_id, owner):
        record = self.store.get(task_id, owner)
        if not record:
            raise TaskNotFoundError()
        return record

    def _admit(self):
        if not self.started:
            raise UnsupportedOperationError("Service is not ready")
        if len(self.jobs) >= self.max_pending:
            raise UnsupportedOperationError("SERVICE_BUSY: retry later", data={"retryable": True})

    async def on_message_send(self, params, context):
        owner = self._owner(params, context)
        self._admit()
        message = params.message
        if message.role != pb.ROLE_USER or not message.message_id:
            raise InvalidParamsError("A user message with messageId is required")
        if len(message.parts) != 1 or message.parts[0].WhichOneof("content") != "data":
            raise ContentTypeNotSupportedError("Supply exactly one data part containing DiagnosticRequest")
        if message.parts[0].media_type not in {"", "application/json"}:
            raise ContentTypeNotSupportedError()
        config = params.configuration
        if config.history_length < 0:
            raise InvalidParamsError("historyLength must be nonnegative")
        if config.HasField("task_push_notification_config"):
            raise PushNotificationNotSupportedError()
        if config.accepted_output_modes and "application/json" not in config.accepted_output_modes:
            raise ContentTypeNotSupportedError("Results require application/json")
        try:
            request = data_to_contract(message.parts[0].data)
            self.service.validate(request)
        except ValidationError as exc:
            raise InvalidParamsError("Invalid DiagnosticRequest", data={"fields": [list(e["loc"]) for e in exc.errors()][:32]}) from None
        except ServiceError as exc:
            raise InvalidParamsError(str(exc), data={"code": exc.code, "requestId": request.workflow.requestId}) from None
        if message.task_id:
            task, original_json = self._get(message.task_id, owner)
            if task.status.state != pb.TASK_STATE_INPUT_REQUIRED:
                raise UnsupportedOperationError("Only input-required tasks accept continuation; repaired source needs a new task")
            original = DiagnosticRequest.model_validate_json(original_json)
            if (request.workflow.workflowId != original.workflow.workflowId or request.code.digest() != original.code.digest()
                    or (request.code.artifactId, request.code.revision) != (original.code.artifactId, original.code.revision)):
                raise InvalidParamsError("Continuation must retain the workflow and code version")
            if message.context_id and message.context_id != task.context_id:
                raise InvalidParamsError("contextId does not match task")
            self._status(task, pb.TASK_STATE_SUBMITTED)
            task.ClearField("artifacts")
            task.history.append(message)
            if len(task.history) > 10:
                del task.history[:-10]
            self.store.save(task, request.model_dump_json())
        else:
            context_id = message.context_id
            if context_id:
                original_json = self.store.context_request(context_id, owner)
                if not original_json:
                    raise TaskNotFoundError("Unknown or inaccessible contextId")
                if DiagnosticRequest.model_validate_json(original_json).workflow.workflowId != request.workflow.workflowId:
                    raise InvalidParamsError("contextId belongs to another workflow")
            else:
                context_id = str(uuid4())
            task = pb.Task(id=str(uuid4()), context_id=context_id, history=[message])
            task.metadata.update({"workflowId": request.workflow.workflowId, "requestId": request.workflow.requestId})
            self._status(task, pb.TASK_STATE_SUBMITTED)
            self.store.insert(task, owner, request.model_dump_json())
        job = asyncio.create_task(self._work(task.id, owner, request))
        self.jobs[task.id] = job
        job.add_done_callback(lambda done, task_id=task.id: self.jobs.pop(task_id, None))
        if not config.return_immediately:
            await asyncio.shield(job)
            task, _ = self._get(task.id, owner)
        if not config.history_length:
            task.ClearField("history")
        elif len(task.history) > config.history_length:
            del task.history[:-config.history_length]
        return task

    async def _work(self, task_id, owner, request):
        async with self.slots:
            task, _ = self._get(task_id, owner)
            if task.status.state != pb.TASK_STATE_SUBMITTED:
                return
            self._status(task, pb.TASK_STATE_WORKING)
            self.store.save(task)
            try:
                result = await asyncio.get_running_loop().run_in_executor(self.executor, partial(self.service.process, request, owner))
                artifact = ParseDict({"artifactId": str(uuid4()), "name": "DiagnosticResult",
                                      "parts": [{"data": result.model_dump(mode="json"), "mediaType": "application/json"}]}, pb.Artifact())
                task.artifacts.append(artifact)
                if result.nextAction == "FIX_ENVIRONMENT":
                    self._status(task, pb.TASK_STATE_FAILED, "EXECUTION_ENVIRONMENT_UNAVAILABLE: see result artifact")
                elif result.nextAction == "PROVIDE_CONTEXT":
                    self._status(task, pb.TASK_STATE_INPUT_REQUIRED, "Provide more feedback for this code version in a new data message")
                else:
                    self._status(task, pb.TASK_STATE_COMPLETED)
            except ServiceError as exc:
                self._status(task, pb.TASK_STATE_FAILED, f"{exc.code}: {exc}")
            except Exception:
                logger.exception("A2A task %s failed", task_id)
                self._status(task, pb.TASK_STATE_FAILED, "INTERNAL_ERROR: diagnosis service failed")
            self.store.save(task)

    async def on_get_task(self, params, context):
        task, _ = self._get(params.id, self._owner(params, context))
        if params.history_length < 0:
            raise InvalidParamsError("historyLength must be nonnegative")
        if not params.history_length:
            task.ClearField("history")
        elif len(task.history) > params.history_length:
            del task.history[:-params.history_length]
        return task

    async def on_list_tasks(self, params, context):
        owner = self._owner(params, context)
        if params.page_size < 0 or params.page_size > 100 or params.history_length < 0:
            raise InvalidParamsError("pageSize must be 0..100 and historyLength nonnegative")
        limit = params.page_size or 50
        try:
            offset = int(base64.urlsafe_b64decode(params.page_token).decode()) if params.page_token else 0
            if offset < 0:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise InvalidParamsError("Invalid pageToken") from None
        after = params.status_timestamp_after.ToDatetime(tzinfo=timezone.utc).timestamp() if params.HasField("status_timestamp_after") else None
        tasks, total = self.store.list(owner, context_id=params.context_id, state=params.status, after=after, limit=limit, offset=offset)
        for task in tasks:
            if not params.include_artifacts:
                task.ClearField("artifacts")
            if not params.history_length:
                task.ClearField("history")
            elif len(task.history) > params.history_length:
                del task.history[:-params.history_length]
        next_token = base64.urlsafe_b64encode(str(offset + len(tasks)).encode()).decode() if offset + len(tasks) < total else ""
        return pb.ListTasksResponse(tasks=tasks, next_page_token=next_token, page_size=limit, total_size=total)

    async def on_cancel_task(self, params, context):
        task, _ = self._get(params.id, self._owner(params, context))
        if task.status.state not in {pb.TASK_STATE_SUBMITTED, pb.TASK_STATE_INPUT_REQUIRED}:
            raise TaskNotCancelableError("Only queued or input-required tasks can be canceled")
        self._status(task, pb.TASK_STATE_CANCELED)
        self.store.save(task)
        return task

    async def on_message_send_stream(self, params, context):
        raise UnsupportedOperationError("Streaming is not enabled; use SendMessage and GetTask")
        yield

    async def on_subscribe_to_task(self, params, context):
        raise UnsupportedOperationError("Task subscriptions are not enabled")
        yield

    async def on_create_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_get_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_list_task_push_notification_configs(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_delete_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_get_extended_agent_card(self, params, context):
        raise ExtendedAgentCardNotConfiguredError()
