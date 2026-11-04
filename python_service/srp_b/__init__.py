"""Public B entry point. Install the shared framework alongside this package."""

__version__ = "0.4.0"


def create_module(state_dir=".interop/local-v2", image="srp-b-python:0.3.0", max_payload_bytes=2 * 1024 * 1024,
                  diagnosis_backend="rules", anthropic_model=None, anthropic_max_tokens=1024,
                  anthropic_timeout_seconds=30, anthropic_base_url=None,
                  anthropic_api_key_env="ANTHROPIC_API_KEY"):
    from .module import BModule

    return BModule(state_dir=state_dir, image=image, max_payload_bytes=max_payload_bytes,
                   diagnosis_backend=diagnosis_backend, anthropic_model=anthropic_model,
                   anthropic_max_tokens=anthropic_max_tokens, anthropic_timeout_seconds=anthropic_timeout_seconds,
                   anthropic_base_url=anthropic_base_url, anthropic_api_key_env=anthropic_api_key_env)
