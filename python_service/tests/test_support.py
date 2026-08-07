from app.sandbox.support import (
    expected_output_matched,
    normalize_language,
    normalize_output,
    truncate_output,
)


def test_normalize_language():
    assert normalize_language("python3") == "python"
    assert normalize_language("py") == "python"
    assert normalize_language("java") == "java"
    assert normalize_language("cpp") is None


def test_output_matching():
    assert normalize_output("5\r\n") == "5"
    assert expected_output_matched("5\n", "5") is True
    assert expected_output_matched("-1\n", "5") is False
    assert expected_output_matched("anything", "") is True


def test_truncate_output():
    text = "a" * 100
    truncated, was_truncated = truncate_output(text, 40)
    assert was_truncated is True
    assert "TRUNCATED" in truncated
    assert len(truncated) <= 100
