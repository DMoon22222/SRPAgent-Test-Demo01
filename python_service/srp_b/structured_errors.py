"""Bounded Python log parsing. Derived observations never replace raw facts."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import PurePosixPath

from reliable_codegen.utils import canonical, digest

MAX_CHARS = 65536
MAX_LINES = 1024
MAX_LINE_CHARS = 4096
MAX_FRAMES = 64
MAX_EXCEPTIONS = 16
VERSION = "python-traceback-v1"
FRAME = re.compile(r'^\s*File "([^"\r\n]{1,2048})"(?:,\s*line ([0-9]{1,9}))?(?:,\s*in ([^\r\n]{1,200}))?\s*$')
SHORT_FRAME = re.compile(r"^(.{1,1024}\.py):([0-9]{1,9}):(?:\s*in (.{1,200}))?\s*$")
SHORT_ERROR = re.compile(r"^(.{1,1024}\.py):([0-9]{1,9}):\s*([A-Za-z_][A-Za-z0-9_.]{0,127})(?::\s*(.*))?$")
EXCEPTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]{0,127})(?::\s*(.*))?$")
NAME_SYMBOL = re.compile(r"name ['\"]([^'\"\r\n]{1,200})['\"] is not defined")
CHAINS = {
    "The above exception was the direct cause of the following exception:": "direct_cause",
    "During handling of the above exception, another exception occurred:": "during_handling",
}


def safe_path(path, known_paths=()):
    """Return a declared relative suffix, or a basename without host directories."""
    value = path.replace("\\", "/")
    for known in sorted(known_paths, key=len, reverse=True):
        normalized = known.replace("\\", "/")
        if value == normalized or value.endswith("/" + normalized):
            return normalized
    if not value.startswith("/") and ":" not in value and ".." not in PurePosixPath(value).parts:
        return value[:512]
    return PurePosixPath(value).name[:512] or None


def _is_exception(name, has_header, has_message):
    short = name.rsplit(".", 1)[-1]
    return short.endswith(("Error", "Exception", "Warning")) or short in {
        "KeyboardInterrupt", "SystemExit", "ExceptionGroup", "BaseExceptionGroup", "TimeoutExpired",
    } or (has_header and has_message)


def parse_python(text, *, known_paths=(), truncated=False):
    """Parse standard and short pytest frames, plus explicit Python chain links."""
    if not isinstance(text, str):
        raise TypeError("Log text must be a string")
    bounded = text[:MAX_CHARS]
    limited = truncated or len(text) > MAX_CHARS
    lines = bounded.splitlines()
    if len(lines) > MAX_LINES:
        limited = True
    frames, exceptions, pending = [], [], []
    group, relation, has_header = 0, "root", False
    for index, original in enumerate(lines[:MAX_LINES]):
        if len(original) > MAX_LINE_CHARS:
            limited = True
        line = original[:MAX_LINE_CHARS].strip()
        exception_line_allowed = not original[:1].isspace()
        if line in CHAINS:
            relation = CHAINS[line]
            continue
        if line.startswith("Traceback (most recent call last):"):
            if exceptions and relation not in {"direct_cause", "during_handling"}:
                group += 1
                relation = "unlinked"
            pending, has_header = [], True
            continue
        if line.startswith("E "):
            line = line[1:].lstrip()
            exception_line_allowed = True
        short_error = SHORT_ERROR.fullmatch(line)
        if short_error and _is_exception(short_error[3], False, short_error[4] is not None):
            path, number, error_type, message = short_error.groups()
            if len(frames) < MAX_FRAMES:
                frame = {"file": safe_path(path, known_paths), "line": int(number) if int(number) > 0 else None,
                         "frame_format": "pytest_error_summary",
                         "function": None, "log_line": index + 1, "raw_line_sha256": digest(original),
                         "path_redacted": safe_path(path, known_paths) != path.replace("\\", "/")}
                frames.append(frame)
                pending.append(frame)
            else:
                limited = True
            line = error_type + (": " + message if message is not None else "")
            exception_line_allowed = True
        match = FRAME.fullmatch(line) or SHORT_FRAME.fullmatch(line)
        if match:
            if len(frames) >= MAX_FRAMES:
                limited = True
                continue
            path, number, function = match.groups()
            frame = {"file": safe_path(path, known_paths), "line": int(number) if number and int(number) > 0 else None,
                     "frame_format": "python_standard" if FRAME.fullmatch(line) else "pytest_short",
                     "function": function.strip() if function else None, "log_line": index + 1,
                     "raw_line_sha256": digest(original),
                     "path_redacted": safe_path(path, known_paths) != path.replace("\\", "/")}
            frames.append(frame)
            pending.append(frame)
            continue
        match = EXCEPTION.fullmatch(line)
        if not exception_line_allowed or not match or not _is_exception(match[1], has_header, match[2] is not None):
            continue
        if len(exceptions) >= MAX_EXCEPTIONS:
            limited = True
            break
        error_type, message = match.groups()
        if exceptions and relation == "unlinked" and not has_header:
            group += 1
        symbol_match = NAME_SYMBOL.search(message or "")
        exceptions.append({
            "error_type": error_type.rsplit(".", 1)[-1], "error_message": (message or "")[:2048],
            "symbol": symbol_match[1] if symbol_match else None,
            "stack_frames": deepcopy(pending), "group": group,
            "relation": relation if exceptions else "root", "log_line": index + 1,
            "raw_line_sha256": digest(original),
        })
        relation, has_header, pending = "unlinked", False, []
    terminal_by_group = {}
    for error in exceptions:
        terminal_by_group[error["group"]] = error
    terminal = exceptions[-1] if exceptions else None
    last_frame = terminal["stack_frames"][-1] if terminal and terminal["stack_frames"] else None
    complete = bool(terminal and terminal["error_message"]) and not limited and not pending
    return {
        "version": VERSION, "language": "python", "parse_status": "success" if complete else "partial" if frames or exceptions else "unavailable",
        "error_type": terminal["error_type"] if terminal else None,
        "error_message": terminal["error_message"] if terminal else None,
        "file": last_frame["file"] if last_frame else None,
        "line": last_frame["line"] if last_frame else None,
        "function": last_frame["function"] if last_frame else None,
        "symbol": terminal["symbol"] if terminal else None,
        "stack_frames": frames, "exception_chain": exceptions,
        "terminal_exceptions": list(terminal_by_group.values()),
        "input_sha256": digest(text), "analyzed_sha256": digest(bounded),
        "input_truncated": limited, "incomplete_stack": bool(pending) and any(f["frame_format"] == "python_standard" for f in pending),
        "limits": {"characters": MAX_CHARS, "lines": MAX_LINES, "frames": MAX_FRAMES, "exceptions": MAX_EXCEPTIONS},
    }


def parse_sources(sources, *, known_paths=()):
    records = []
    for source in sources[:64]:
        parsed = parse_python(source["text"], known_paths=known_paths, truncated=source.get("truncated", False))
        parsed.update(origin={key: source["reference"][key] for key in ("kind", "artifact_id", "pointer")},
                      representation=source.get("representation", "raw_log"),
                      raw_fact_sha256=source.get("raw_fact_sha256"), failed_test=source.get("failed_test"))
        records.append(parsed)
    return {"version": VERSION, "layer": "parsed_facts", "records": records,
            "sources_truncated": len(sources) > 64, "raw_facts_replaced": False}


def validate_parsed(bundle, sources, *, known_paths=()):
    """Replay the bounded parser; a source hash alone does not validate a frame."""
    return canonical(bundle) == canonical(parse_sources(sources, known_paths=known_paths))


def wire_frames(bundle):
    """Project onto the existing public StackFrame shape, with safe paths."""
    result, seen = [], set()
    for record in bundle["records"]:
        for frame in record["stack_frames"]:
            key = (frame["file"], frame["line"], frame["function"])
            if key in seen:
                continue
            seen.add(key)
            result.append({"location": {"file": frame["file"], "line_start": frame["line"],
                                        "line_end": frame["line"], "symbol": frame["function"]},
                           "message": "Parsed from supplied Python traceback; see structured evidence provenance."})
            if len(result) == MAX_FRAMES:
                return result
    return result


def known_workspace_paths(payload):
    paths = [item["path"] for item in payload["code_artifact"]["files"]]
    paths += [item["path"] for item in payload.get("test_artifact", {}).get("files", [])]
    manifest = payload.get("execution_context", {}).get("build_manifest", payload.get("build_manifest", {}))
    return paths + [item["path"] for item in manifest.get("supporting_files", [])]


def evidence_sources(failure_source, evidence, logs=None):
    """Build explicitly labeled representations from existing evidence only."""
    static = failure_source["kind"] == "static"
    fact = failure_source["static_report" if static else "execution_result"]
    sources = []
    for reference in evidence:
        pointer = reference["pointer"]
        if static:
            value = fact["findings"][int(pointer.rsplit("/", 1)[1])]
            text, representation = value["message"], "static_finding_message"
        elif reference["kind"] == "test_result":
            value = fact["test_case_results"][int(pointer.rsplit("/", 1)[1])]
            text, representation = value["message"] or "", "test_message"
            error = value["error_type"]
            if error and error + ":" not in text and "Traceback (most recent call last):" not in text:
                text, representation = error + ": " + text, "test_error_type_plus_message"
        else:
            name = pointer[1:]
            value = fact[name]
            text = logs.get(name, "") if logs is not None else value.get("text", "")
            representation = "raw_log"
        sources.append({"text": text, "reference": deepcopy(reference), "representation": representation,
                        "raw_fact_sha256": digest(canonical(value)),
                        "truncated": bool(value.get("truncated", False)),
                        "failed_test": value.get("test_id")})
    return sources
