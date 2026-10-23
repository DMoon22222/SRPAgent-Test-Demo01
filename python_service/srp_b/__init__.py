"""Public B entry point. Install the shared framework alongside this package."""

__version__ = "0.3.1"


def create_module(state_dir=".interop/local-v2", image="srp-b-python:0.3.0", max_payload_bytes=2 * 1024 * 1024):
    from .module import BModule

    return BModule(state_dir=state_dir, image=image, max_payload_bytes=max_payload_bytes)
