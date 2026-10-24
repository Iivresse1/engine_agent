"""本地 token 账单：usage_metadata 按 thread × 角色聚合（输入/输出/总数）。

Q39 钉板：账单纯本地持久化，不外发云端，LangSmith 明确不引入（spec『可观测』节）。
挂钩点 = ModelClient 协议的 role / thread_id 参数（model_client.py）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from project_agent.model_client import ModelResult, ModelUsage


@dataclass(frozen=True)
class RoleUsage:
    """单 thread 内单角色的用量小计：输入 / 输出 / 总数 / 调用次数。"""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenLedger:
    """账单存储：按 thread × 角色聚合 usage_metadata，本地 JSON 持久化。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, RoleUsage]] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._data = {
                thread: {
                    role: RoleUsage(**fields) for role, fields in roles.items()
                }
                for thread, roles in raw.items()
            }

    def record(self, thread_id: str, role: str, usage: ModelUsage) -> None:
        """一次模型调用的用量入账（输入/输出累加，调用次数 +1）并落盘。"""
        roles = self._data.setdefault(thread_id, {})
        current = roles.get(role, RoleUsage())
        roles[role] = RoleUsage(
            input_tokens=current.input_tokens + usage.input_tokens,
            output_tokens=current.output_tokens + usage.output_tokens,
            calls=current.calls + 1,
        )
        self._flush()

    def usage_for(self, thread_id: str) -> dict[str, RoleUsage]:
        """按角色分账：返回该 thread 下各角色的用量小计。"""
        return dict(self._data.get(thread_id, {}))

    def _flush(self) -> None:
        """账单只落本地盘（Q39 红线：无任何网络上报路径）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            thread: {role: asdict(u) for role, u in roles.items()}
            for thread, roles in self._data.items()
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class MeteredModel:
    """ModelClient 包装聚合层：用量自动入账，协议形状保持不变。

    满足 ModelClient 协议（结构化子类型），可包装任何 ModelClient
    （测试替身 ScriptedModel 或后续票的真模型客户端）。
    """

    def __init__(self, inner: Any, ledger: TokenLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    def complete(
        self, messages: Sequence[Mapping[str, Any]], *, role: str, thread_id: str
    ) -> ModelResult:
        result = self._inner.complete(messages, role=role, thread_id=thread_id)
        if result.usage is not None:
            self._ledger.record(thread_id, role, result.usage)
        return result
