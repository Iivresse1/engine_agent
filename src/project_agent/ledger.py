"""本地 token 账单：usage_metadata 按 thread × 角色聚合（输入/输出/总数）。

Q39 钉板：账单纯本地持久化，不外发云端，LangSmith 明确不引入（spec『可观测』节）。
挂钩点 = ModelClient 协议的 role / thread_id 参数（model_client.py）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from project_agent.model_client import ModelUsage


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
    """账单存储：按 thread × 角色聚合 usage_metadata。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, RoleUsage]] = {}

    def record(self, thread_id: str, role: str, usage: ModelUsage) -> None:
        """一次模型调用的用量入账（输入/输出累加，调用次数 +1）。"""
        roles = self._data.setdefault(thread_id, {})
        current = roles.get(role, RoleUsage())
        roles[role] = RoleUsage(
            input_tokens=current.input_tokens + usage.input_tokens,
            output_tokens=current.output_tokens + usage.output_tokens,
            calls=current.calls + 1,
        )

    def usage_for(self, thread_id: str) -> dict[str, RoleUsage]:
        """按角色分账：返回该 thread 下各角色的用量小计。"""
        return dict(self._data.get(thread_id, {}))
