"""Internal contract for repository runners."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.schemas import RepositoryExecution


@dataclass(frozen=True)
class RepositoryRunSpec:
    """Server-approved runner inputs that contain no original workspace path."""

    runner: str
    test_targets: tuple[str, ...]
    timeout_seconds: int
    benchmark: str = ""


class RepositoryRunner(ABC):
    """Execute tests against a disposable repository snapshot."""

    @abstractmethod
    def run(
        self,
        snapshot_path: Path,
        spec: RepositoryRunSpec,
    ) -> RepositoryExecution:
        """Return repository test execution data without analyzing failures."""
