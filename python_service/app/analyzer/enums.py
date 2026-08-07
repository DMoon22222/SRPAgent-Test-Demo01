ALLOWED_FAILED_STAGES = {
    "PRE_CHECK",
    "COMPILE",
    "RUNTIME",
    "TEST",
    "SANDBOX",
    "UNKNOWN",
}

ALLOWED_ERROR_TYPES = {
    "COMPILE_ERROR",
    "RUNTIME_ERROR",
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "LOGIC_ERROR",
    "API_MISUSE",
    "KNOWLEDGE_GAP",
    "ENVIRONMENT_ERROR",
    "SANDBOX_ERROR",
    "UNKNOWN",
}

ALLOWED_ERROR_SUBTYPES = {
    "SYNTAX_ERROR",
    "MISSING_SYMBOL",
    "TYPE_MISMATCH",
    "INDENTATION_ERROR",
    "NULL_POINTER",
    "INDEX_OUT_OF_BOUNDS",
    "DIVIDE_BY_ZERO",
    "DEPENDENCY_MISSING",
    "API_SIGNATURE_MISMATCH",
    "OUTPUT_FORMAT_ERROR",
    "ALGORITHM_ERROR",
    "INFINITE_LOOP",
    "RESOURCE_LIMIT",
    "SANDBOX_INTERNAL_ERROR",
    "UNKNOWN",
}


def normalize_enum_value(value: str | None) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    return text or "UNKNOWN"


def normalize_failed_stage(value: str | None, fallback: str = "UNKNOWN") -> tuple[str, bool]:
    original = normalize_enum_value(value)
    mapping = {
        "RUN": "RUNTIME",
        "EXECUTION": "RUNTIME",
        "EXECUTE": "RUNTIME",
        "SYNTAX_CHECK": "COMPILE",
        "COMPILE_ERROR": "COMPILE",
        "RUNTIME_ERROR": "RUNTIME",
        "ASSERTION": "TEST",
        "ASSERTION_ERROR": "TEST",
        "TEST_EXECUTION": "TEST",
    }
    normalized = mapping.get(original, original)
    if normalized in ALLOWED_FAILED_STAGES:
        return normalized, normalized != original
    return fallback, True


def normalize_error_type(value: str | None, fallback: str = "UNKNOWN") -> tuple[str, bool]:
    original = normalize_enum_value(value)
    mapping = {
        "SYNTAXERROR": "COMPILE_ERROR",
        "SYNTAX_ERROR": "COMPILE_ERROR",
        "INDENTATIONERROR": "COMPILE_ERROR",
        "ZERO_DIVISION_ERROR": "RUNTIME_ERROR",
        "ZERODIVISIONERROR": "RUNTIME_ERROR",
        "ASSERTIONERROR": "WRONG_ANSWER",
        "ASSERTION_ERROR": "WRONG_ANSWER",
        "TIMEOUT": "TIME_LIMIT_EXCEEDED",
        "TIME_LIMIT": "TIME_LIMIT_EXCEEDED",
        "MODULE_NOT_FOUND_ERROR": "API_MISUSE",
        "MODULENOTFOUNDERROR": "API_MISUSE",
        "IMPORTERROR": "API_MISUSE",
        "IMPORT_ERROR": "API_MISUSE",
    }
    normalized = mapping.get(original, original)
    if normalized in ALLOWED_ERROR_TYPES:
        return normalized, normalized != original
    return fallback, True


def normalize_error_subtype(value: str | None, fallback: str = "UNKNOWN") -> tuple[str, bool]:
    original = normalize_enum_value(value)
    mapping = {
        "INVALID_SYNTAX": "SYNTAX_ERROR",
        "SYNTAXERROR": "SYNTAX_ERROR",
        "INDENTATIONERROR": "INDENTATION_ERROR",
        "DIVISION_BY_ZERO": "DIVIDE_BY_ZERO",
        "ZERO_DIVISION_ERROR": "DIVIDE_BY_ZERO",
        "ZERODIVISIONERROR": "DIVIDE_BY_ZERO",
        "RETURN_VALUE_MISMATCH": "ALGORITHM_ERROR",
        "ASSERTIONERROR": "ALGORITHM_ERROR",
        "ASSERTION_ERROR": "ALGORITHM_ERROR",
        "TIMEOUT": "INFINITE_LOOP",
        "TIME_LIMIT": "INFINITE_LOOP",
        "MODULE_NOT_FOUND_ERROR": "DEPENDENCY_MISSING",
        "MODULENOTFOUNDERROR": "DEPENDENCY_MISSING",
        "IMPORTERROR": "DEPENDENCY_MISSING",
        "IMPORT_ERROR": "DEPENDENCY_MISSING",
    }
    normalized = mapping.get(original, original)
    if normalized in ALLOWED_ERROR_SUBTYPES:
        return normalized, normalized != original
    return fallback, True


def has_invalid_enum(result: dict) -> bool:
    stage, stage_changed = normalize_failed_stage(result.get("failedStage"))
    error_type, type_changed = normalize_error_type(result.get("errorType"))
    subtype, subtype_changed = normalize_error_subtype(result.get("errorSubtype"))
    return (
        stage_changed
        or type_changed
        or subtype_changed
        or stage not in ALLOWED_FAILED_STAGES
        or error_type not in ALLOWED_ERROR_TYPES
        or subtype not in ALLOWED_ERROR_SUBTYPES
    )
