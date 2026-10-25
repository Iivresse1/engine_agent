"""本地 token 账单：usage_metadata 按 thread × 角色聚合（输入/输出/总数），纯本地（04 票）。

Q39 钉板：账单不外发云端，LangSmith 明确不引入（spec『可观测』节）。
"""

from __future__ import annotations

from pathlib import Path

from project_agent.ledger import TokenLedger
from project_agent.model_client import ModelUsage


def test_record_aggregates_per_role_and_thread(tmp_path: Path):
    ledger = TokenLedger(tmp_path / "ledger.json")
    ledger.record("t1", "actor", ModelUsage(input_tokens=100, output_tokens=50))
    ledger.record("t1", "actor", ModelUsage(input_tokens=10, output_tokens=5))
    ledger.record("t1", "verifier", ModelUsage(input_tokens=30, output_tokens=20))
    ledger.record("t2", "actor", ModelUsage(input_tokens=7, output_tokens=3))

    t1 = ledger.usage_for("t1")
    # 手算期望值：actor 两次调用 100+10 / 50+5；verifier 一次 30/20
    assert t1["actor"].input_tokens == 110
    assert t1["actor"].output_tokens == 55
    assert t1["actor"].total_tokens == 165
    assert t1["actor"].calls == 2
    assert t1["verifier"].input_tokens == 30
    assert t1["verifier"].total_tokens == 50
    assert t1["verifier"].calls == 1
    # thread 隔离：t2 的账不混入 t1
    assert set(ledger.usage_for("t2")) == {"actor"}
    assert ledger.usage_for("t2")["actor"].total_tokens == 10
    # 未知 thread 零账
    assert ledger.usage_for("never") == {}


def test_ledger_persists_across_restart(tmp_path: Path):
    """会话重启后可查：新实例从盘上载入既有账目。"""
    path = tmp_path / "ledger.json"
    TokenLedger(path).record("t1", "actor", ModelUsage(input_tokens=100, output_tokens=50))
    TokenLedger(path).record("t1", "verifier", ModelUsage(input_tokens=30, output_tokens=20))

    revived = TokenLedger(path)
    assert revived.usage_for("t1")["actor"].total_tokens == 150
    assert revived.usage_for("t1")["verifier"].calls == 1
    # 重启后继续记账，账目延续
    revived.record("t1", "actor", ModelUsage(input_tokens=10, output_tokens=5))
    assert revived.usage_for("t1")["actor"].input_tokens == 110
    again = TokenLedger(path)
    assert again.usage_for("t1")["actor"].total_tokens == 165
