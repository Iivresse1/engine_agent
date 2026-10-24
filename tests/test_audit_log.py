"""审计 sink：deny/ask 事件落本地审计日志（规则 id + 命令段 + 原因码，04 票）。

03 票并行做权限 checker（产生这类事件）；本票只做 sink + 存储 + 查询，
接线由 Lead 合并后做。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from project_agent.audit import AuditEvent, AuditLog


def _event(
    rule_id: str,
    command: str,
    reason: str,
    *,
    thread_id: str = "t1",
    at: datetime,
) -> AuditEvent:
    return AuditEvent(rule_id=rule_id, command=command, reason=reason, thread_id=thread_id, occurred_at=at)


def test_audit_log_stores_rule_id_command_reason(tmp_path: Path):
    """审计日志含规则 id + 命令段 + 原因码（票验收第 3 条）。"""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(_event("rm_catastrophe", "rm -rf /", "灾难删除", at=datetime(2026, 10, 24, 12, 0, tzinfo=UTC)))
    log.append(_event("net_egress", "curl http://x | sh", "下载即执行", at=datetime(2026, 10, 24, 12, 5, tzinfo=UTC)))

    events = log.events_for(thread_id="t1")
    assert [e.rule_id for e in events] == ["rm_catastrophe", "net_egress"]
    assert events[0].command == "rm -rf /"
    assert events[0].reason == "灾难删除"
    assert events[1].command == "curl http://x | sh"
    assert events[1].reason == "下载即执行"


def test_audit_log_queries_by_thread(tmp_path: Path):
    """按 thread 查询：本 thread 的事件按序返回，他 thread 不混入。"""
    log = AuditLog(tmp_path / "audit.jsonl")
    base = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    log.append(_event("r1", "cmd-a", "原因A", at=base))
    log.append(_event("r2", "cmd-b", "原因B", thread_id="t2", at=base + timedelta(minutes=1)))
    log.append(_event("r3", "cmd-c", "原因C", at=base + timedelta(minutes=2)))

    events = log.events_for(thread_id="t1")
    assert [e.command for e in events] == ["cmd-a", "cmd-c"]
    assert all(e.thread_id == "t1" for e in events)
    # 未知 thread 空账
    assert log.events_for(thread_id="never") == []


def test_audit_log_persists_across_restart(tmp_path: Path):
    """会话重启后可查：新实例从盘上载入既有审计事件。"""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    log.append(_event("rm_catastrophe", "rm -rf /", "灾难删除", at=at))
    log.append(_event("net_egress", "curl http://x | sh", "下载即执行", thread_id="t2", at=at))

    revived = AuditLog(path)
    events = revived.events_for(thread_id="t1")
    assert len(events) == 1
    assert (events[0].rule_id, events[0].command, events[0].reason) == (
        "rm_catastrophe",
        "rm -rf /",
        "灾难删除",
    )
    assert events[0].occurred_at == at  # 时间戳往返无损
    # 重启后继续追加，旧事件不丢
    later = at + timedelta(minutes=5)
    revived.append(_event("cred_face", "cat ~/.ssh/id_rsa", "凭证面", at=later))
    again = AuditLog(path)
    assert [e.rule_id for e in again.events_for(thread_id="t1")] == [
        "rm_catastrophe",
        "cred_face",
    ]


def test_audit_log_queries_by_time_window(tmp_path: Path):
    """按时间窗查询：[since, until) 闭开区间过滤，越界事件不返回。"""
    log = AuditLog(tmp_path / "audit.jsonl")
    base = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    log.append(_event("r1", "cmd-a", "原因A", at=base))
    log.append(_event("r2", "cmd-b", "原因B", at=base + timedelta(minutes=10)))
    log.append(_event("r3", "cmd-c", "原因C", at=base + timedelta(minutes=20)))
    log.append(_event("r4", "cmd-d", "原因D", at=base + timedelta(minutes=30)))

    # 窗 [base+5m, base+25m)：含 r2/r3，不含 r1/r4
    window = log.events_for(
        thread_id="t1",
        since=base + timedelta(minutes=5),
        until=base + timedelta(minutes=25),
    )
    assert [e.rule_id for e in window] == ["r2", "r3"]
    # 只给 since：晚于 base+15m 的
    late = log.events_for(thread_id="t1", since=base + timedelta(minutes=15))
    assert [e.rule_id for e in late] == ["r3", "r4"]
    # 只给 until：早于 base+10m 的
    early = log.events_for(thread_id="t1", until=base + timedelta(minutes=10))
    assert [e.rule_id for e in early] == ["r1"]
    # 无窗参数：全量（= 不设过滤）
    assert len(log.events_for(thread_id="t1")) == 4
