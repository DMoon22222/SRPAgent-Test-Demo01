from pathlib import Path

import pytest

from app.repository.pytest_parser import (
    MAX_FAILURE_EXCERPT_CHARS,
    MAX_FAILURE_MESSAGE_CHARS,
    PytestReportError,
    parse_pytest_junit,
)


def write_report(tmp_path: Path, xml: str) -> Path:
    report = tmp_path / "junit.xml"
    report.write_text(xml, encoding="utf-8")
    return report


def test_all_passed_xml(tmp_path):
    report = parse_pytest_junit(
        write_report(
            tmp_path,
            '<testsuite tests="2" failures="0" errors="0" skipped="0">'
            '<testcase file="tests/test_x.py" name="test_a" />'
            '<testcase file="tests/test_x.py" name="test_b" />'
            "</testsuite>",
        )
    )

    assert report.summary.model_dump() == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
    }
    assert report.failures == ()


def test_failure_uses_file_and_name_for_test_id(tmp_path):
    report = parse_pytest_junit(
        write_report(
            tmp_path,
            '<testsuite tests="1" failures="1" errors="0" skipped="0">'
            '<testcase classname="TestMath" file="tests/test_math.py" '
            'line="17" name="test_add">'
            '<failure message="assert 4 == 5">traceback excerpt</failure>'
            "</testcase></testsuite>",
        )
    )

    failure = report.failures[0]
    assert report.summary.failed == 1
    assert failure.testId == "tests/test_math.py::test_add"
    assert failure.location == "tests/test_math.py:17"
    assert failure.message == "assert 4 == 5"
    assert failure.excerpt == "traceback excerpt"


def test_failures_errors_and_skips_are_mapped(tmp_path):
    report = parse_pytest_junit(
        write_report(
            tmp_path,
            '<testsuites tests="4" failures="1" errors="1" skipped="1">'
            '<testsuite tests="4" failures="1" errors="1" skipped="1">'
            '<testcase classname="mod" name="passed" />'
            '<testcase classname="mod" name="failed"><failure>failed</failure></testcase>'
            '<testcase classname="mod" name="errored"><error>error</error></testcase>'
            '<testcase classname="mod" name="skipped"><skipped /></testcase>'
            "</testsuite></testsuites>",
        )
    )

    assert report.summary.total == 4
    assert report.summary.failed == 2
    assert report.summary.passed == 1
    assert report.summary.skipped == 1
    assert [failure.testId for failure in report.failures] == [
        "mod::failed",
        "mod::errored",
    ]


def test_missing_summary_fields_are_derived_from_testcases(tmp_path):
    report = parse_pytest_junit(
        write_report(
            tmp_path,
            '<testsuite><testcase name="failed"><failure>bad</failure></testcase>'
            '<testcase name="skipped"><skipped /></testcase></testsuite>',
        )
    )

    assert report.summary.total == 2
    assert report.summary.failed == 1
    assert report.summary.skipped == 1
    assert report.summary.passed == 0


def test_failure_list_is_bounded_but_summary_is_complete(tmp_path):
    cases = "".join(
        f'<testcase classname="mod" name="test_{index}"><failure>bad</failure></testcase>'
        for index in range(4)
    )
    report = parse_pytest_junit(
        write_report(
            tmp_path,
            f'<testsuite tests="4" failures="4" errors="0" skipped="0">{cases}</testsuite>',
        ),
        failure_limit=2,
    )

    assert report.summary.failed == 4
    assert len(report.failures) == 2
    assert report.failure_list_truncated is True


def test_failure_text_is_truncated(tmp_path):
    long_message = "m" * (MAX_FAILURE_MESSAGE_CHARS + 100)
    long_excerpt = "e" * (MAX_FAILURE_EXCERPT_CHARS + 100)
    report = parse_pytest_junit(
        write_report(
            tmp_path,
            '<testsuite tests="1" failures="1" errors="0" skipped="0">'
            f'<testcase name="test_x"><failure message="{long_message}">'
            f"{long_excerpt}</failure></testcase></testsuite>",
        )
    )

    assert len(report.failures[0].message) == MAX_FAILURE_MESSAGE_CHARS
    assert len(report.failures[0].excerpt) == MAX_FAILURE_EXCERPT_CHARS


def test_missing_empty_invalid_and_oversized_reports_are_rejected(tmp_path):
    with pytest.raises(PytestReportError, match="missing"):
        parse_pytest_junit(tmp_path / "missing.xml")

    empty = write_report(tmp_path, "")
    with pytest.raises(PytestReportError, match="empty"):
        parse_pytest_junit(empty)

    invalid = write_report(tmp_path, "<testsuite>")
    with pytest.raises(PytestReportError, match="invalid XML"):
        parse_pytest_junit(invalid)

    oversized = write_report(tmp_path, "<testsuite />")
    with pytest.raises(PytestReportError, match="size limit"):
        parse_pytest_junit(oversized, max_bytes=2)


@pytest.mark.parametrize("declaration", ["<!DOCTYPE foo>", "<!ENTITY x 'x'>"])
def test_dangerous_xml_declarations_are_rejected(tmp_path, declaration):
    report = write_report(tmp_path, f"{declaration}<testsuite />")

    with pytest.raises(PytestReportError, match="forbidden XML"):
        parse_pytest_junit(report)
