from app.analyzer.error_signal_extractor import extract_signals, summarize_error_signal


def test_zero_division_signal():
    signals = extract_signals("Traceback\nZeroDivisionError: division by zero")
    assert "DIVIDE_BY_ZERO" in signals or "ZeroDivisionError" in signals


def test_syntax_error_signal():
    signals = extract_signals("File \"Main.py\", line 1\nSyntaxError: '(' was never closed")
    assert "SYNTAX_ERROR" in signals or "SyntaxError" in signals
    assert "Main.py:1" in signals


def test_java_missing_symbol_signal():
    signals = extract_signals("Main.java:3: error: cannot find symbol")
    assert "MISSING_SYMBOL" in signals or "cannot find symbol" in signals


def test_timeout_signal():
    signals = extract_signals("status=TIME_LIMIT_EXCEEDED timeout=true")
    assert any("TIME_LIMIT" in signal or "timeout" in signal for signal in signals)


def test_summary_format():
    summary = summarize_error_signal("ZeroDivisionError")
    assert summary.startswith("【规则信号摘要】")
