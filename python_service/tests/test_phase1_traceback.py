"""Parser provenance, boundedness and incomplete/host-path handling."""

from copy import deepcopy

import pytest

from srp_b.structured_errors import (
    MAX_CHARS,
    MAX_EXCEPTIONS,
    MAX_FRAMES,
    parse_python,
    parse_sources,
    validate_parsed,
    wire_frames,
)

STANDARD = 'Traceback (most recent call last):\n  File "/workspace/src/main.py", line 25, in calculate\n    return missing_value\nNameError: name \'missing_value\' is not defined'


def source(text=STANDARD):
    return [{"text": text, "reference": {"kind": "log_span", "artifact_id": "execution-test", "pointer": "/stderr", "summary": "traceback"}}]


def test_standard_traceback_and_declared_path():
    result = parse_python(STANDARD, known_paths=["src/main.py"])
    assert result["parse_status"] == "success"
    assert (result["error_type"], result["file"], result["line"], result["function"], result["symbol"]) == (
        "NameError", "src/main.py", 25, "calculate", "missing_value",
    )


def test_multilayer_stack_keeps_frame_order():
    text = 'Traceback (most recent call last):\n  File "src/main.py", line 2, in add\n  File "src/main.py", line 7, in helper\nIndexError: list index out of range'
    result = parse_python(text)
    assert [f["function"] for f in result["stack_frames"]] == ["add", "helper"]
    assert result["line"] == 7


@pytest.mark.parametrize("marker,relation", [
    ("The above exception was the direct cause of the following exception:", "direct_cause"),
    ("During handling of the above exception, another exception occurred:", "during_handling"),
])
def test_explicit_exception_chains_use_terminal_exception(marker, relation):
    text = STANDARD + "\n\n" + marker + '\n\nTraceback (most recent call last):\n  File "src/main.py", line 30, in handler\nValueError: rejected'
    result = parse_python(text)
    assert result["error_type"] == "ValueError"
    assert [e["error_type"] for e in result["exception_chain"]] == ["NameError", "ValueError"]
    assert result["exception_chain"][-1]["relation"] == relation
    assert len(result["terminal_exceptions"]) == 1


def test_independent_errors_do_not_become_a_causal_chain():
    result = parse_python(STANDARD + "\nKeyError: 'other'")
    assert len(result["terminal_exceptions"]) == 2
    assert result["exception_chain"][-1]["relation"] == "unlinked"


@pytest.mark.parametrize("text", ["NameError: missing", "NameError"])
def test_missing_frame_has_null_location(text):
    result = parse_python(text)
    assert result["file"] is result["line"] is result["function"] is None
    assert not result["stack_frames"]


def test_missing_line_is_not_guessed():
    result = parse_python('Traceback (most recent call last):\n  File "src/main.py", in calculate\nNameError: missing')
    assert result["file"] == "src/main.py" and result["line"] is None


def test_syntax_location_without_function():
    result = parse_python('  File "src/main.py", line 1\n    def add(a,b)\n                ^\nSyntaxError: expected colon')
    assert result["error_type"] == "SyntaxError" and result["line"] == 1
    assert result["function"] is None


def test_short_pytest_exception_line_has_a_real_location():
    result = parse_python("tests/test_main.py:4: AssertionError: assert -1 == 5")
    assert result["error_type"] == "AssertionError"
    assert result["file"] == "tests/test_main.py" and result["line"] == 4
    assert result["function"] is None


@pytest.mark.parametrize("text", ["garbled <<<<", "", "INFO: quoted NameError is only a string"])
def test_unparseable_and_quoted_signals_remain_unavailable(text):
    result = parse_python(text)
    assert result["parse_status"] == "unavailable" and not result["exception_chain"]


def test_truncation_keeps_partial_status():
    assert parse_python(STANDARD, truncated=True)["parse_status"] == "partial"
    assert parse_python(STANDARD + "\nTraceback (most recent call last):\n  File \"src/main.py\", line 40, in handler")["parse_status"] == "partial"


def test_long_input_and_deep_stacks_are_bounded():
    text = "Traceback (most recent call last):\n" + '  File "src/main.py", line 1, in recurse\n' * 2000 + "NameError: missing"
    result = parse_python(text)
    assert len(result["stack_frames"]) <= MAX_FRAMES and result["input_truncated"]
    assert len(result["exception_chain"]) <= MAX_EXCEPTIONS
    assert len(text) > MAX_CHARS


def test_windows_absolute_host_path_is_not_exposed_in_parsed_fields():
    result = parse_python(STANDARD.replace("/workspace/src/main.py", r"C:\Users\private\project\src\main.py"), known_paths=["src/main.py"])
    assert result["file"] == "src/main.py"
    assert "private" not in str(result["stack_frames"])


def test_provenance_replay_detects_tampered_frame_and_raw_log():
    sources = source()
    original = deepcopy(sources)
    bundle = parse_sources(sources, known_paths=["src/main.py"])
    assert validate_parsed(bundle, sources, known_paths=["src/main.py"])
    assert sources == original
    changed = deepcopy(bundle)
    changed["records"][0]["stack_frames"][0]["line"] = 999
    assert not validate_parsed(changed, sources, known_paths=["src/main.py"])
    assert not validate_parsed(bundle, source(STANDARD.replace("25", "26")), known_paths=["src/main.py"])
    assert bundle["records"][0]["origin"]["pointer"] == "/stderr"


def test_wire_projection_uses_existing_stackframe_contract():
    from reliable_codegen.contracts import ContractRegistry

    frames = wire_frames(parse_sources(source(), known_paths=["src/main.py"]))
    assert frames
    for frame in frames:
        ContractRegistry().validate("StackFrame", frame)


def test_indented_source_identifier_is_not_a_terminal_exception():
    text = 'Traceback (most recent call last):\n  File "src/main.py", line 1, in add\n    NameError\nValueError: rejected'
    result = parse_python(text)
    assert [error["error_type"] for error in result["exception_chain"]] == ["ValueError"]


def test_subprocess_timeout_expired_is_an_explicit_exception():
    result = parse_python("TimeoutExpired: timed out after 1 second")
    assert result["error_type"] == "TimeoutExpired" and result["parse_status"] == "success"


def test_pytest_assertion_frame_without_exception_token_is_not_a_cut_off_traceback():
    result = parse_python("tests/test_main.py:4: in test_add\n    assert add(2, 3) == 5\nE   assert -1 == 5")
    assert result["stack_frames"] and not result["incomplete_stack"]
    assert result["error_type"] is None
