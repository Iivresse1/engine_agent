"""LLM 边界协议：ModelClient——01 票定接口形状；17 票加工具调用能力。

role / thread_id 参数是 04 票 token 账单按 thread×角色聚合的挂钩点。

17 票扩展：`complete_with_tools` 是**可选能力**（Protocol 无法表达"可选方法"，
故用 `hasattr` 探测）——支持工具调用的客户端返回 `ToolAwareResult`（带
`tool_calls`），不支持的退回 `complete` 的纯文本行为。这样：
- 既有桩模型（只有 complete）零改动即通过；
- 真模型客户端实现 `complete_with_tools` 才启用工具环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelResult:
    text: str
    usage: ModelUsage | None = None


@dataclass(frozen=True)
class ToolCall:
    """模型请求的一次工具调用（与 OpenAI `tool_calls` 元素同构）。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolAwareResult:
    """带工具请求的模型回复；`tool_calls` 为空即"本轮终稿"。"""

    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: ModelUsage | None = None


@runtime_checkable
class ModelClient(Protocol):
    def complete(
        self, messages: Sequence[Mapping[str, Any]], *, role: str, thread_id: str
    ) -> ModelResult: ...


@runtime_checkable
class ToolAwareModelClient(Protocol):
    """支持 function-calling 的客户端（17 票工具环的模型侧）。"""

    def complete_with_tools(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        role: str,
        thread_id: str,
    ) -> ToolAwareResult: ...


def supports_tools(model: Any) -> bool:
    """模型是否支持 function calling（`hasattr` 探测，不 import 具体实现）。"""
    return callable(getattr(model, "complete_with_tools", None))


__all__ = [
    "ModelClient",
    "ModelResult",
    "ModelUsage",
    "ToolAwareModelClient",
    "ToolAwareResult",
    "ToolCall",
    "supports_tools",
]
