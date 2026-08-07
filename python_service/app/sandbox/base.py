from abc import ABC, abstractmethod

from app.schemas import ExecuteAndAnalyzeRequest, Execution


class CodeSandbox(ABC):
    @abstractmethod
    def run(self, request: ExecuteAndAnalyzeRequest) -> Execution:
        pass

    @abstractmethod
    def check_syntax(self, request: ExecuteAndAnalyzeRequest) -> Execution:
        pass
