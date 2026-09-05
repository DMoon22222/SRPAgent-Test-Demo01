"""Bounded parsing of untrusted pytest JUnit XML reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.schemas import RepositoryTestFailure, RepositoryTestSummary

MAX_JUNIT_XML_BYTES = 5 * 1024 * 1024
MAX_REPOSITORY_FAILURES = 5
MAX_FAILURE_MESSAGE_CHARS = 500
MAX_FAILURE_EXCERPT_CHARS = 1000


class PytestReportError(ValueError):
    """Raised when a JUnit report cannot be consumed safely."""


@dataclass(frozen=True)
class PytestReport:
    summary: RepositoryTestSummary
    failures: tuple[RepositoryTestFailure, ...]
    failure_list_truncated: bool = False


def parse_pytest_junit(
    report_path: Path,
    *,
    max_bytes: int = MAX_JUNIT_XML_BYTES,
    failure_limit: int = MAX_REPOSITORY_FAILURES,
) -> PytestReport:
    """Parse a pytest JUnit report without reading an unbounded file."""
    try:
        size = report_path.stat().st_size
    except OSError as exc:
        raise PytestReportError("pytest JUnit report is missing") from exc
    if size <= 0:
        raise PytestReportError("pytest JUnit report is empty")
    if size > max_bytes:
        raise PytestReportError("pytest JUnit report exceeds the size limit")

    try:
        with report_path.open("rb") as report_file:
            payload = report_file.read(max_bytes + 1)
    except OSError as exc:
        raise PytestReportError("pytest JUnit report could not be read") from exc
    if len(payload) > max_bytes:
        raise PytestReportError("pytest JUnit report exceeds the size limit")
    upper_payload = payload.upper()
    if b"<!DOCTYPE" in upper_payload or b"<!ENTITY" in upper_payload:
        raise PytestReportError("pytest JUnit report contains forbidden XML")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise PytestReportError("pytest JUnit report is invalid XML") from exc

    root_name = _local_name(root.tag)
    if root_name not in {"testsuite", "testsuites"}:
        raise PytestReportError("pytest JUnit report has an unsupported root")

    testcases = [item for item in root.iter() if _local_name(item.tag) == "testcase"]
    tests, failures, errors, skipped = _summary_counts(root, testcases)
    failed = max(0, failures + errors)
    skipped = max(0, skipped)
    total = max(0, tests, failed + skipped, len(testcases))
    passed = max(0, total - failed - skipped)

    parsed_failures: list[RepositoryTestFailure] = []
    total_failure_elements = 0
    for testcase in testcases:
        for child in testcase:
            if _local_name(child.tag) not in {"failure", "error"}:
                continue
            total_failure_elements += 1
            if len(parsed_failures) >= max(0, failure_limit):
                continue
            parsed_failures.append(_parse_failure(testcase, child))

    return PytestReport(
        summary=RepositoryTestSummary(
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
        ),
        failures=tuple(parsed_failures),
        failure_list_truncated=total_failure_elements > len(parsed_failures),
    )


def _summary_counts(root, testcases) -> tuple[int, int, int, int]:
    names = ("tests", "failures", "errors", "skipped")
    values = tuple(_nonnegative_int(root.attrib.get(name)) for name in names)
    if not any(name in root.attrib for name in names):
        child_suites = [
            child for child in root if _local_name(child.tag) == "testsuite"
        ]
        if child_suites:
            values = tuple(
                sum(
                    _nonnegative_int(suite.attrib.get(name))
                    for suite in child_suites
                )
                for name in names
            )

    observed_failures = sum(
        1
        for testcase in testcases
        for child in testcase
        if _local_name(child.tag) == "failure"
    )
    observed_errors = sum(
        1
        for testcase in testcases
        for child in testcase
        if _local_name(child.tag) == "error"
    )
    observed_skipped = sum(
        1
        for testcase in testcases
        for child in testcase
        if _local_name(child.tag) == "skipped"
    )
    observed = (
        len(testcases),
        observed_failures,
        observed_errors,
        observed_skipped,
    )
    return tuple(max(value, actual) for value, actual in zip(values, observed))


def _parse_failure(testcase, failure) -> RepositoryTestFailure:
    name = testcase.attrib.get("name", "unknown")
    file_name = testcase.attrib.get("file", "")
    class_name = testcase.attrib.get("classname", "")
    test_id = f"{file_name}::{name}" if file_name else "::".join(
        part for part in (class_name, name) if part
    )
    line = testcase.attrib.get("line", "")
    location = f"{file_name}:{line}" if file_name and line else file_name or class_name
    body = "".join(failure.itertext()).strip()
    message = failure.attrib.get("message", "") or _first_line(body)
    return RepositoryTestFailure(
        testId=_truncate(message=test_id, limit=MAX_FAILURE_MESSAGE_CHARS),
        message=_truncate(message=message, limit=MAX_FAILURE_MESSAGE_CHARS),
        location=_truncate(message=location, limit=MAX_FAILURE_MESSAGE_CHARS),
        excerpt=_truncate(message=body, limit=MAX_FAILURE_EXCERPT_CHARS),
    )


def _nonnegative_int(value: str | None) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _first_line(value: str) -> str:
    return value.splitlines()[0] if value else ""


def _truncate(*, message: str, limit: int) -> str:
    if len(message) <= limit:
        return message
    return message[: max(0, limit - 3)] + "..."


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
