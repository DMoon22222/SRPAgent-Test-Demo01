"""Contract-only interface for future repository runners."""

from abc import ABC, abstractmethod

from app.schemas import RepositoryExecution, RepositoryExecutionRequest


class RepositoryRunner(ABC):
    """Execute a validated repository request in a future isolated runner."""

    @abstractmethod
    def run(self, request: RepositoryExecutionRequest) -> RepositoryExecution:
        """Return repository test execution data without analyzing failures."""
