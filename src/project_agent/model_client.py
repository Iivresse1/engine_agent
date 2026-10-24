"""LLM 边界协议：ModelClient——01 票仅定接口形状（测试替身依赖），真模型接入在后续票。

role / thread_id 参数是 04 票 token 账单按 thread×角色聚合的挂钩点。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelResult:
    text: str
    usage: ModelUsage | None = None


@runtime_checkable
class ModelClient(Protocol):
    def complete(
        self, messages: Sequence[Mapping[str, Any]], *, role: str, thread_id: str
    ) -> ModelResult: ...
