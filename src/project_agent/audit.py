"""审计 sink：shell 审批的 deny/ask 事件落本地审计日志（04 票）。

事件形状 = 规则 id + 命令段 + 原因码（+ thread + 发生时刻，供查询）。
03 票的权限 checker 产生事件；本模块只做 sink + 存储 + 查询，
接线（checker → sink）由 Lead 合并后完成。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class AuditEvent:
    """一条 shell 审批审计记录：规则 id + 命令段 + 原因码。"""

    rule_id: str
    command: str
    reason: str
    thread_id: str
    occurred_at: datetime


def _to_json(event: AuditEvent) -> dict[str, str]:
    return {
        "rule_id": event.rule_id,
        "command": event.command,
        "reason": event.reason,
        "thread_id": event.thread_id,
        "occurred_at": event.occurred_at.isoformat(),
    }


@dataclass(frozen=True)
class _Window:
    """查询时间窗 [since, until]（闭开区间：含 since、不含 until）。"""

    since: datetime | None = None
    until: datetime | None = None

    def contains(self, at: datetime) -> bool:
        if self.since is not None and at < self.since:
            return False
        if self.until is not None and at >= self.until:
            return False
        return True


class AuditLog:
    """审计日志存储：JSONL 追加写，本地持久化（无任何网络上报路径）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._events: list[AuditEvent] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                self._events.append(
                    AuditEvent(
                        rule_id=data["rule_id"],
                        command=data["command"],
                        reason=data["reason"],
                        thread_id=data["thread_id"],
                        occurred_at=datetime.fromisoformat(data["occurred_at"]),
                    )
                )

    def append(self, event: AuditEvent) -> None:
        """一条审计事件入账并落盘。"""
        self._events.append(event)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_to_json(event), ensure_ascii=False) + "\n")

    def events_for(
        self,
        *,
        thread_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AuditEvent]:
        """按 thread 查询审计事件（可选时间窗），时间升序返回。"""
        window = _Window(since=since, until=until)
        events = [e for e in self._events if e.thread_id == thread_id and window.contains(e.occurred_at)]
        return sorted(events, key=lambda e: e.occurred_at)
