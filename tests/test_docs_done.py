"""11 票切片 2：docs_done 断点（验收 1）。

纯代码节点：task_complete 真 → 交付概览 + ["构建 demo", "跳过"] 决议；
自由文本决议三态——building / skipped / 无匹配重发（零副作用）。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import docs_done_node

DONE_TODOS = [{"content": "写 README", "status": "completed"}]


def _base_state(**overrides):
    state = {
        "task_brief": "做个记账 CLI",
        "build_way": "way3",
        "todos": DONE_TODOS,
        "task_complete": True,
        "actor_messages": [HumanMessage(content="开始")],
    }
    state.update(overrides)
    return state


def _cfg(thread: str = "t-docs") -> dict:
    return {"configurable": {"thread_id": thread}}


# —— 节点：docs_done 断点 payload 形状 ——


def test_docs_done_breakpoint_payload_shape():
    updates = docs_done_node(_base_state())
    assert updates["turn_end_reason"] == "docs_done"
    payload = updates["turn_end_payload"]
    assert set(payload) == {"deliverables_overview", "options"}
    assert payload["options"] == ["构建 demo", "跳过"]
    # way3 三份交付物：概览含份数与文件名
    assert "交付物集 3 份已就绪" in payload["deliverables_overview"]
    assert "README.md" in payload["deliverables_overview"]
    assert "TODO.md" in payload["deliverables_overview"]
    assert "目录树.txt" in payload["deliverables_overview"]
    # 纯代码节点：不调模型（无 model 参数即结构性保证）


def test_docs_done_payload_way2_single_deliverable():
    updates = docs_done_node(_base_state(build_way="way2"))
    assert "交付物集 1 份已就绪（IDEA.md）" == updates["turn_end_payload"][
        "deliverables_overview"
    ]


# —— 决议消费：building 三态之一（不含 turn_end——后节点写） ——


@pytest.mark.parametrize("answer", ["构建 demo", "demo", "1"], ids=["zh", "en", "index"])
def test_resolution_build_sets_demo_phase_building_without_turn_end(answer):
    updates = docs_done_node(_base_state(resolution_inputs=[answer]))
    assert updates["demo_phase"] == "building"
    assert updates["resolution_inputs"] == []
    assert "turn_end_reason" not in updates  # 同轮接 DEMO_AGENT，后节点写断点


# —— 决议消费：skipped 三态之二（round 断点 "已跳过 demo"） ——


@pytest.mark.parametrize("answer", ["跳过", "不", "2"], ids=["zh", "no", "index"])
def test_resolution_skip_sets_demo_phase_skipped_with_round_end(answer):
    updates = docs_done_node(_base_state(resolution_inputs=[answer]))
    assert updates["demo_phase"] == "skipped"
    assert updates["resolution_inputs"] == []
    assert updates["turn_end_reason"] == "round"
    assert updates["turn_end_payload"]["round_output"] == "已跳过 demo"


# —— 无匹配：重发 docs_done（复用校验后的 payload，零副作用） ——


def test_unmatched_resolution_resends_docs_done_payload():
    state = _base_state(
        resolution_inputs=["随便聊聊"],
        turn_end_reason="docs_done",
        turn_end_payload={
            "deliverables_overview": "交付物集 3 份已就绪（README.md, TODO.md, 目录树.txt）",
            "options": ["构建 demo", "跳过"],
        },
    )
    updates = docs_done_node(state)
    assert "demo_phase" not in updates
    assert updates["resolution_inputs"] == []
    assert updates["turn_end_reason"] == "docs_done"
    assert updates["turn_end_payload"] == state["turn_end_payload"]


def test_unmatched_resolution_rebuilds_payload_when_stale():
    """上轮 payload 不可复用（协议外形状）→ 按当前 way 重建，仍零副作用。"""
    state = _base_state(
        resolution_inputs=["嗯"],
        turn_end_payload={"bogus": "x"},
    )
    updates = docs_done_node(state)
    assert updates["turn_end_payload"]["options"] == ["构建 demo", "跳过"]
    assert "demo_phase" not in updates


# —— 图接线：入口行 7 改道 DOCS_DONE + 决议断点回放 ——


def test_graph_entry_row7_reaches_docs_done_breakpoint():
    app = build_graph(checkpointer=InMemorySaver())
    r = app.invoke(_base_state(), _cfg("g-docs-1"))
    assert r["turn_end_reason"] == "docs_done"
    assert r["turn_end_payload"]["options"] == ["构建 demo", "跳过"]
    assert "交付物集 3 份已就绪" in r["turn_end_payload"]["deliverables_overview"]


def test_graph_skip_resolution_ends_round_and_persists_skipped():
    app = build_graph(checkpointer=InMemorySaver())
    cfg = _cfg("g-docs-2")
    app.invoke(_base_state(), cfg)
    r = app.invoke({"resolution_inputs": ["跳过"]}, cfg)
    assert r["demo_phase"] == "skipped"
    assert r["turn_end_reason"] == "round"
    assert r["turn_end_payload"]["round_output"] == "已跳过 demo"
    # 已决后再输入：docs_done 节点幂等零副作用（断点收轮，终检票 12 接管）
    r2 = app.invoke({"resolution_inputs": ["跳过"]}, cfg)
    assert r2["demo_phase"] == "skipped"
    assert r2["turn_end_reason"] == "round"
