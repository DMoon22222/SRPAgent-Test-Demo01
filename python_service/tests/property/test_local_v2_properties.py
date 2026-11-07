"""Three bounded properties; generated inputs never reach a real executor."""

import hashlib
import tempfile
from pathlib import Path

import pytest
from reliable_codegen.transport import TransportError
from srp_b import create_module
from srp_b.module import EXECUTE
from srp_b.samples import request
from srp_b.sandbox import empty_observation

hypothesis = pytest.importorskip("hypothesis", reason="Optional test-only dependency")
strategies = pytest.importorskip("hypothesis.strategies")
bounded = hypothesis.settings(max_examples=30, deadline=2000, derandomize=True, database=None)


class CountingBackend:
    def __init__(self):
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        return {**empty_observation(), "execution_calls": 1}


def module_with_counter(directory, counter):
    module = create_module(state_dir=str(directory))
    module.runner = counter
    return module


@bounded
@hypothesis.given(
    mode=strategies.sampled_from(("path", "hash")),
    name=strategies.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20),
    prefix=strategies.sampled_from(("../", "/", "C:/", "src/../")),
)
def test_invalid_artifact_never_reaches_executor(mode, name, prefix):
    with tempfile.TemporaryDirectory(prefix="b-property-artifact-") as directory:
        counter = CountingBackend()
        module = module_with_counter(directory, counter)
        envelope = request(EXECUTE)
        artifact = envelope["payload"]["code_artifact"]
        if mode == "path":
            artifact["files"][0]["path"] = prefix + name + ".py"
        else:
            candidate = hashlib.sha256(name.encode()).hexdigest()
            if candidate == artifact["content_hash"]:
                candidate = ("1" if candidate[0] == "0" else "0") + candidate[1:]
            artifact["content_hash"] = candidate
        try:
            response = module.call(EXECUTE, envelope)
            assert response["payload"]["status"] in {"error", "blocked"}
        except TransportError:
            pass
        assert counter.calls == 0


@bounded
@hypothesis.given(
    limit=strategies.integers(0, 5),
    used=strategies.integers(0, 5),
    granted=strategies.integers(0, 6),
    mismatched_revision=strategies.booleans(),
)
def test_budget_and_grant_boundary(limit, used, granted, mismatched_revision):
    with tempfile.TemporaryDirectory(prefix="b-property-budget-") as directory:
        counter = CountingBackend()
        module = module_with_counter(directory, counter)
        envelope = request(EXECUTE)
        budget, grant = (envelope["payload"][key] for key in ("budget", "call_grant"))
        used = min(used, limit)
        budget["limits"]["execution_calls"] = limit
        budget["used"]["execution_calls"] = used
        budget["reserved"]["execution_calls"] = 0
        budget["remaining"]["execution_calls"] = limit - used
        grant["max_execution_calls"] = granted
        if mismatched_revision:
            grant["budget_revision"] += 1
        allowed = not mismatched_revision and 1 <= granted <= limit - used
        response = module.call(EXECUTE, envelope)["payload"]
        assert counter.calls == int(allowed)
        assert response["usage"]["execution_calls"] == int(allowed)
        assert response["status"] == ("completed" if allowed else "blocked")
        assert counter.calls <= max(0, granted)


@bounded
@hypothesis.given(marker=strategies.text(max_size=40), repeats=strategies.integers(1, 3))
def test_durable_replay_and_identity_conflict(marker, repeats):
    with tempfile.TemporaryDirectory(prefix="b-property-replay-") as directory:
        state = Path(directory) / "state"
        counter = CountingBackend()
        envelope = request(EXECUTE)
        envelope["extensions"] = {"property_marker": marker}
        response = module_with_counter(state, counter).call(EXECUTE, envelope)
        for _ in range(repeats):
            assert module_with_counter(state, counter).call(EXECUTE, envelope) == response
        envelope["extensions"]["property_marker"] = marker + "-different"
        with pytest.raises(TransportError, match="IDEMPOTENCY_CONFLICT"):
            module_with_counter(state, counter).call(EXECUTE, envelope)
        assert counter.calls == 1
