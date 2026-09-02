from __future__ import annotations

from typing import Any, Iterable
#工具系统的汇总与校验层，负责调用所有Provider的discover()，合并工具，检测重名，验证Tool Spec结构，过滤本次Runtime可用工具

class ToolRegistry:
    def __init__(self, providers: Iterable[Any]):
        self.providers = list(providers)

    #调取每个Provider的discover()，合并其工具，校验结构并检测重名，最终返回Pico.tools
    def discover(self, context) -> dict[str, dict]:
        #保存最终工具表
        tools: dict[str, dict] = {}
        #保存工具来源
        owners: dict[str, str] = {}

        for provider in self.providers:
            provided = provider.discover(context)
            if not isinstance(provided, dict):
                raise TypeError(
                    f"tool provider '{provider.name}' must return dict"
                )

            for name, spec in provided.items():
                self._validate_spec(provider.name, name, spec)

                if name in tools:
                    raise ValueError(
                        f"tool name collision: '{name}' is provided by both "
                        f"'{owners[name]}' and '{provider.name}'"
                    )

                tools[name] = dict(spec)
                owners[name] = provider.name

        return tools

    #检查单个工具是否包含schema、risky、description、run等必要字段
    @staticmethod
    def _validate_spec(provider_name: str, name: str, spec: dict) -> None:
        required = ("schema", "risky", "description", "run")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"tool provider '{provider_name}' returned empty tool name"
            )
        if not isinstance(spec, dict):
            raise TypeError(f"tool '{name}' must be a dict")

        missing = [field for field in required if field not in spec]
        if missing:
            raise ValueError(
                f"tool '{name}' missing fields: {', '.join(missing)}"
            )
        if not isinstance(spec["schema"], dict):
            raise TypeError(f"tool '{name}' schema must be a dict")
        if not isinstance(spec["risky"], bool):
            raise TypeError(f"tool '{name}' risky must be bool")
        if not callable(spec["run"]):
            raise TypeError(f"tool '{name}' run must be callable")

    #按照任务白名单过滤工具；若白名单中有未发现的工具立刻报错
    @staticmethod
    def filter_allowed(
        tools: dict[str, dict],
        allowed_tools: tuple[str, ...] | None,
    ) -> dict[str, dict]:
        if allowed_tools is None:
            return tools

        unknown = [name for name in allowed_tools if name not in tools]
        if unknown:
            raise ValueError(
                f"unknown allowed tool: {', '.join(unknown)}"
            )

        allowed = set(allowed_tools)
        return {
            name: tool
            for name, tool in tools.items()
            if name in allowed
        }