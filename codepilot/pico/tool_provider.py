from __future__ import annotations

from abc import ABC, abstractmethod
from functools import partial
from typing import Any

from . import tools as toolkit


ToolSpec = dict[str, Any]


class ToolProvider(ABC):
    """工具来源抽象；负责发现，不负责绕过执行治理。"""

    name: str

    @abstractmethod
    def discover(self, context) -> dict[str, ToolSpec]:
        """返回统一内部 ToolSpec。"""


class BuiltinToolProvider(ToolProvider):
    """包装现有 tools.py，而不复制任何内置工具实现。"""

    name = "builtin"

    def discover(self, context) -> dict[str, ToolSpec]:
        discovered = toolkit.build_tool_registry(context)
        normalized: dict[str, ToolSpec] = {}

        for tool_name, tool in discovered.items():
            spec = dict(tool)
            spec["provider"] = self.name
            spec["validate"] = partial(
                toolkit.validate_tool,
                context,
                tool_name,
            )
            spec["example"] = toolkit.tool_example(tool_name)
            normalized[tool_name] = spec

        return normalized
