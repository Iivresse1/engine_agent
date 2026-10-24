"""MeteredModel：ModelClient 包装聚合层——协议形状不变，用量自动入账（04 票）。"""

from __future__ import annotations

from pathlib import Path

from project_agent.ledger import MeteredModel, TokenLedger
from project_agent.model_client import ModelClient, ModelResult, ModelUsage
from tests.doubles.fake_model import ScriptedModel


def test_metered_model_records_fake_usage_per_role(tmp_path: Path):
    """假模型上报假 usage_metadata，账单按角色分账数字正确（票验收第 1 条）。"""
    scripted = ScriptedModel([
        ModelResult(text="主线回答", usage=ModelUsage(input_tokens=100, output_tokens=50)),
        ModelResult(text="校验回答", usage=ModelUsage(input_tokens=30, output_tokens=20)),
        ModelResult(text="主线追问", usage=ModelUsage(input_tokens=10, output_tokens=5)),
    ])
    ledger = TokenLedger(tmp_path / "ledger.json")
    model: ModelClient = MeteredModel(scripted, ledger)

    r1 = model.complete([{"role": "user", "content": "做"}], role="actor", thread_id="t1")
    r2 = model.complete([], role="verifier", thread_id="t1")
    r3 = model.complete([], role="actor", thread_id="t1")

    # 协议形状不变：原样返回 ModelResult（含 usage）
    assert (r1.text, r1.usage.input_tokens, r1.usage.output_tokens) == ("主线回答", 100, 50)
    assert r2.text == "校验回答"
    assert r3.text == "主线追问"
    # 包装透传 role/thread_id（替身可证）
    assert [c["role"] for c in scripted.calls] == ["actor", "verifier", "actor"]
    assert all(c["thread_id"] == "t1" for c in scripted.calls)
    # 账单数字：手算期望
    t1 = ledger.usage_for("t1")
    assert (t1["actor"].input_tokens, t1["actor"].output_tokens) == (110, 55)
    assert t1["actor"].calls == 2
    assert (t1["verifier"].input_tokens, t1["verifier"].output_tokens) == (30, 20)
    assert t1["verifier"].calls == 1
    # MeteredModel 自身结构化满足协议（测试替身同构，01 票挂靠点不变）
    assert isinstance(model, ModelClient)
