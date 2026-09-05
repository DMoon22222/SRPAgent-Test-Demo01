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
    }
    return {key: value for key, value in values.items() if value != ""}


settings = Settings()
