import os
from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field, model_validator

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    BaseSettings = BaseModel

    def SettingsConfigDict(**kwargs):
        return kwargs


class Settings(BaseSettings):
    dashscope_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DASHSCOPE_API_KEY", "LLM_API_KEY"),
    )
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("DASHSCOPE_BASE_URL", "LLM_BASE_URL"),
    )
    dashscope_model: str = Field(
        default="qwen-plus",
        validation_alias=AliasChoices("DASHSCOPE_MODEL", "LLM_MODEL_ID"),
    )

    sandbox_mode: str = "docker"
    sandbox_timeout_ms: int = 5000
    sandbox_docker_image: str = "srp-code-sandbox:latest"
    sandbox_docker_memory: str = "256m"
    sandbox_docker_cpus: str = "1"
    sandbox_docker_pids_limit: str = "64"
    sandbox_max_output_chars: int = 12000
    repository_allowed_root: str = ""
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    interop_api_token: str = ""
    interop_allow_local_execution: bool = False
    interop_public_url: str = "http://127.0.0.1:8000"
    a2a_store_path: str = ".interop/tasks.sqlite3"
    a2a_workers: int = Field(default=2, ge=1, le=8)
    a2a_max_pending: int = Field(default=32, ge=1, le=128)
    mcp_workers: int = Field(default=2, ge=1, le=8)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    def __init__(self, **data):
        if BaseSettings is BaseModel:
            data = {**_fallback_settings_data(), **data}
        super().__init__(**data)

    @model_validator(mode="after")
    def fill_empty_alias_values(self) -> "Settings":
        if not self.dashscope_base_url:
            self.dashscope_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if not self.dashscope_model:
            self.dashscope_model = "qwen-plus"
        return self

def _load_dotenv(path: str) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _fallback_settings_data() -> dict[str, str]:
    env = {**_load_dotenv(".env"), **os.environ}

    def pick(*names: str) -> str:
        for name in names:
            value = env.get(name)
            if value:
                return value
        return ""

    values = {
        "dashscope_api_key": pick("DASHSCOPE_API_KEY", "LLM_API_KEY"),
        "dashscope_base_url": pick("DASHSCOPE_BASE_URL", "LLM_BASE_URL"),
        "dashscope_model": pick("DASHSCOPE_MODEL", "LLM_MODEL_ID"),
        "sandbox_mode": pick("SANDBOX_MODE"),
        "sandbox_timeout_ms": pick("SANDBOX_TIMEOUT_MS"),
        "sandbox_docker_image": pick("SANDBOX_DOCKER_IMAGE"),
        "sandbox_docker_memory": pick("SANDBOX_DOCKER_MEMORY"),
        "sandbox_docker_cpus": pick("SANDBOX_DOCKER_CPUS"),
        "sandbox_docker_pids_limit": pick("SANDBOX_DOCKER_PIDS_LIMIT"),
        "sandbox_max_output_chars": pick("SANDBOX_MAX_OUTPUT_CHARS"),
        "repository_allowed_root": pick("REPOSITORY_ALLOWED_ROOT"),
        "llm_timeout_seconds": pick("LLM_TIMEOUT_SECONDS"),
        "interop_api_token": pick("INTEROP_API_TOKEN"),
        "interop_allow_local_execution": pick("INTEROP_ALLOW_LOCAL_EXECUTION"),
        "interop_public_url": pick("INTEROP_PUBLIC_URL"),
        "a2a_store_path": pick("A2A_STORE_PATH"),
        "a2a_workers": pick("A2A_WORKERS"),
        "a2a_max_pending": pick("A2A_MAX_PENDING"),
        "mcp_workers": pick("MCP_WORKERS"),
    }
    return {key: value for key, value in values.items() if value != ""}


settings = Settings()
