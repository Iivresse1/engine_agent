"""可编程假模型：按脚本顺序出牌并记录调用（LLM 边界测试替身）。

满足 project_agent.model_client.ModelClient 协议（结构化子类型）。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping, Sequence

from project_agent.model_client import ModelResult, ModelUsage


class ScriptedModel:
    def __init__(self, outputs: Sequence[str | ModelResult]) -> None:
        self._outputs: deque[str | ModelResult] = deque(outputs)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, messages: Sequence[Mapping[str, Any]], *, role: str, thread_id: str
    ) -> ModelResult:
        self.calls.append(
            {"role": role, "thread_id": thread_id, "messages": [dict(m) for m in messages]}
        )
        if not self._outputs:
            raise AssertionError("ScriptedModel 脚本耗尽：调用次数超过预置输出数")
        out = self._outputs.popleft()
        if isinstance(out, ModelResult):
            return out
        return ModelResult(text=str(out), usage=ModelUsage(input_tokens=10, output_tokens=5))
