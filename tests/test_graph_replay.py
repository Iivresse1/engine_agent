"""主接缝回放：invoke(自由文本) → 轮终 state；断点续跑零真模型。"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph

pytestmark = pytest.mark.replay


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def _cfg(thread: str = "t1") -> dict:
    return {"configurable": {"thread_id": thread}}


def test_three_round_breakpoint_replay():
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)

    r1 = app.invoke(_say("我想做一个记账 CLI"), _cfg())
    assert r1["task_brief"] == "我想做一个记账 CLI"
    assert r1["turn_end_reason"] == "round"
    assert r1["turn_end_payload"]["round_output"]

    r2 = app.invoke(_say("完整文档"), _cfg())
    assert r2["build_way"] == "way4"
    assert r2["task_brief"] == "我想做一个记账 CLI"  # 断点续跑：状态延续

    r3 = app.invoke(_say("继续"), _cfg())
    assert "占位" in r3["turn_end_payload"]["round_output"]  # 相位推进到 default
    humans = [m for m in r3["actor_messages"] if isinstance(m, HumanMessage)]
    assert len(humans) == 3  # 融合累积，无丢失无重复


def test_state_restored_across_app_instances():
    """END 后同 thread 再 invoke：从 START 重跑且 state 恢复（版本敏感行为实测）。"""
    saver = InMemorySaver()
    app1 = build_graph(checkpointer=saver)
    app1.invoke(_say("原始想法"), _cfg())
    app1.invoke(_say("轻方式"), _cfg())

    app2 = build_graph(checkpointer=saver)
    r = app2.invoke(_say("继续"), _cfg())
    assert r["task_brief"] == "原始想法"
    assert r["build_way"] == "way2"
    assert "占位" in r["turn_end_payload"]["round_output"]  # 跳过 ask_tasks/build_ways


def test_ask_tasks_node_is_idempotent_on_reentry():
    from project_agent.nodes import ask_tasks_node

    state = {"actor_messages": [HumanMessage("新文本")], "task_brief": "已定的简报"}
    updates = ask_tasks_node(state)
    assert "task_brief" not in updates  # 已有简报不被改写（可重入）


def test_build_ways_node_is_idempotent_on_reentry():
    from project_agent.nodes import build_ways_node

    state = {"actor_messages": [HumanMessage("完整文档")], "build_way": "way1"}
    updates = build_ways_node(state)
    assert "build_way" not in updates  # 已定方式不被改写（可重入）


def test_uninterpretable_input_yields_fresh_round_end_not_stale():
    """回归（冒烟发现）：解释不了的输入必须写新断点，不得残留渲染上轮 turn_end。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)

    r1 = app.invoke(_say("我想做记账 CLI"), _cfg())
    r2 = app.invoke(_say("随便说什么都不含关键词"), _cfg())

    assert r2["turn_end_reason"] == "round"
    assert "未识别构建方式" in r2["turn_end_payload"]["round_output"]
    assert r2["turn_end_payload"] != r1["turn_end_payload"]  # 不是上轮残留


def test_build_ways_node_uninterpretable_writes_fresh_end():
    from project_agent.nodes import build_ways_node

    state = {"actor_messages": [HumanMessage("xyzabc")]}
    updates = build_ways_node(state)
    assert updates["turn_end_reason"] == "round"
    assert "未识别" in updates["turn_end_payload"]["round_output"]
