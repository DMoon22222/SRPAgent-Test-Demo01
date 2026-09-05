"""Repository execution extension points."""

from app.repository.base import RepositoryRunner, RepositoryRunSpec
from app.repository.diagnosis import diagnose_repository_execution
from app.repository.docker_runner import DockerPytestRepositoryRunner
from app.repository.workspace import (
    RepositorySnapshot,
    RepositoryWorkspaceError,
    RepositoryWorkspaceManager,
)

__all__ = [
    "DockerPytestRepositoryRunner",
    "RepositoryRunSpec",
    "RepositoryRunner",
    "RepositorySnapshot",
    "RepositoryWorkspaceError",
    "RepositoryWorkspaceManager",
    "diagnose_repository_execution",
]
