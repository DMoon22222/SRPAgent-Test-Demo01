from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvalConfig:
    api_base_url: str = "http://localhost:8080"
    execute_and_analyze_url: str = "http://localhost:8080/api/execute-and-analyze"
    analyze_error_url: str = "http://localhost:8080/api/analyze-error"
    execute_only_url: str = "http://localhost:8080/api/execute-and-analyze"
    pass_marker: str = "__HUMANEVAL_PASS__"
    request_timeout_sec: int = 60
    max_tasks: int = 10
    result_dir: Path = Path(__file__).parent / "results"


config = EvalConfig()
