"""Check the integration adapter without credentials, Docker or network access."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from scripts import run_abc_integration as integration


def test_adapter_preserves_prompt_response_and_usage_and_limits_calls():
    calls, client_options, requests = [], [], []
    response = SimpleNamespace(model_dump=lambda: {"model": "deepseek-flash", "usage": {"total_tokens": 17}})

    class Client:
        def __init__(self, **options):
            client_options.append(options)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **arguments):
            requests.append(arguments)
            return response

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    provider = {"model": "deepseek-flash", "base_url": "https://api.deepseek.com", "max_calls": 1, "timeout_seconds": 30}
    adapter = integration.DeepSeekAdapter(provider, "private-test-token", calls, ["hidden-test-body"], lambda: None, Client)
    create = adapter.factory("decide")().chat.completions.create
    prompt = [{"role": "user", "content": "Check numeric addition"}]
    assert create(model="qwen-plus", messages=prompt, max_tokens=123) is response
    assert requests[0]["messages"] == prompt and requests[0]["max_tokens"] == 123
    assert requests[0]["model"] == "deepseek-flash"
    assert client_options[0]["max_retries"] == 0
    assert calls[0]["response"]["usage"]["total_tokens"] == 17
    assert "private-test-token" not in json.dumps(calls)
    with pytest.raises(RuntimeError, match="call limit"):
        create(model="qwen-plus", messages=prompt)
    assert len(requests) == 1


@pytest.mark.parametrize("body", ["hidden-test-body", "private-test-token"])
def test_adapter_blocks_protected_or_credential_content_before_client_creation(body):
    def unexpected_client(**_options):
        raise AssertionError("No client should be created")

    adapter = integration.DeepSeekAdapter({"max_calls": 1}, "private-test-token", [], ["hidden-test-body"], lambda: None, unexpected_client)
    with pytest.raises(RuntimeError, match="Protected data"):
        adapter.factory("assess")().chat.completions.create(messages=[{"content": body}])
    assert adapter.calls == []


def test_adapter_error_does_not_persist_provider_message_or_retry():
    calls, attempts = [], []

    def failing_client(**_options):
        attempts.append(True)
        raise RuntimeError("provider echoed private-test-token")

    provider = {"model": "deepseek-flash", "base_url": "https://api.deepseek.com", "max_calls": 1, "timeout_seconds": 30}
    adapter = integration.DeepSeekAdapter(provider, "private-test-token", calls, [], lambda: None, failing_client)
    with pytest.raises(RuntimeError, match="DEEPSEEK_assess_RuntimeError") as error:
        adapter.factory("assess")().chat.completions.create(messages=[{"content": "public task"}])
    assert len(attempts) == 1 and calls[0]["status"] == "failed"
    assert "private-test-token" not in str(error.value) + json.dumps(calls)


def test_default_cli_only_checks_local_inputs(monkeypatch, capsys):
    monkeypatch.setattr(integration, "preflight", lambda _config: {"local_check": True})

    def unexpected(*_args, **_options):
        raise AssertionError("Check-only must not request credentials or execute a run")

    monkeypatch.setattr(integration.getpass, "getpass", unexpected)
    monkeypatch.setattr(integration, "run", unexpected)
    assert integration.main([]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "check_only"


def test_config_rejects_credential_values_before_inspecting_sources():
    config = json.loads(integration.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    changed = deepcopy(config)
    changed["provider"]["api_key"] = "private-test-token"
    with pytest.raises(ValueError, match="no credential values"):
        integration.preflight(changed)
