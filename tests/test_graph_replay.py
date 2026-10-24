"""主接缝回放：invoke(融合更新) → 轮终 state；断点续跑零真模型。

02 起 build_ways 走 choice:build_way 断点 + 决议通道（resolution_inputs），
回放输入按 fusion_update 语义构造（无 reducer 整覆写：[*existing, text]）。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_build_ways_node

pytestmark = pytest.mark.replay


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def _resolve(state: dict, text: str) -> dict:
    """REPL 融合端语义：resolution_inputs 无 reducer，发送整列表。"""
    return {"resolution_inputs": [*(state.get("resolution_inputs") or []), text]}


def _cfg(thread: str = "t1") -> dict:
    return {"configurable": {"thread_id": thread}}


def test_three_round_breakpoint_replay():
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)

    r1 = app.invoke(_say("我想做一个记账 CLI"), _cfg())
    assert r1["task_brief"] == "我想做一个记账 CLI"
    assert r1["turn_end_reason"] == "round"
    assert r1["turn_end_payload"]["round_output"]

    r2 = app.invoke(_say("无关键词闲聊"), _cfg())
    assert r2["turn_end_reason"] == "choice:build_way"  # 首入 build_ways：发 choice 断点
    assert r2["turn_end_payload"]["options"] == ["对话", "轻 grill", "简化文档", "完整文档"]

    r3 = app.invoke(_resolve(r2, "用完整文档"), _cfg())
    assert r3["build_way"] == "way4"
    assert r3["task_brief"] == "我想做一个记账 CLI"  # 断点续跑：状态延续
    assert r3["turn_end_reason"] == "round"
    assert r3["resolution_inputs"] == []  # 决议后通道清空


def test_state_restored_across_app_instances():
    """END 后同 thread 再 invoke：从 START 重跑且 state 恢复（版本敏感行为实测）。"""
    saver = InMemorySaver()
    app1 = build_graph(checkpointer=saver)
    app1.invoke(_say("原始想法"), _cfg())
    r_choice = app1.invoke(_say("轻方式"), _cfg())
    app1.invoke(_resolve(r_choice, "轻"), _cfg())

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
    state = {"actor_messages": [HumanMessage("完整文档")], "build_way": "way1"}
    updates = make_build_ways_node(None)(state)
    assert "build_way" not in updates  # 已定方式不被改写（可重入）


def test_uninterpretable_resolution_reshows_choice_not_stale():
    """解释不了的决议输入：清空通道并重发 choice（复用上轮 payload），零 model 调用。"""
    from tests.doubles.fake_model import ScriptedModel

    saver = InMemorySaver()
    model = ScriptedModel(["way3|理由"])  # 仅首次 choice 触模型
    app = build_graph(checkpointer=saver, model=model)

    app.invoke(_say("我想做记账 CLI"), _cfg())
    r_choice = app.invoke(_say("嗯"), _cfg())
    assert len(model.calls) == 1
    r2 = app.invoke(_resolve(r_choice, "随便说什么都不含关键词"), _cfg())

    assert r2["turn_end_reason"] == "choice:build_way"
    assert r2["turn_end_payload"] == r_choice["turn_end_payload"]  # 复用重发
    assert r2["resolution_inputs"] == []
    assert len(model.calls) == 1  # 复用重发：零重复 ModelClient 调用


def test_round_payload_carries_todo_board():
    """spec 断点协议表 round 行：payload = 轮产出 + todo 板。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    r = app.invoke(_say("我想做记账 CLI"), _cfg())
    assert r["turn_end_payload"]["todo_board"] == []

    from project_agent.nodes import ask_tasks_node

    state = {
        "actor_messages": [HumanMessage("新任务")],
        "todos": [
            {"content": "搭骨架", "status": "completed"},
            {"content": "写文档", "status": "in_progress"},
        ],
    }
    updates = ask_tasks_node(state)
    board = updates["turn_end_payload"]["todo_board"]
    assert board == ["completed: 搭骨架", "in_progress: 写文档"]


def test_breakpoint_persists_across_processes(tmp_path):
    """票 L11『turn_end 落盘可查』：sqlite checkpointer 跨进程续跑。"""
    from project_agent.graph import sqlite_checkpointer

    db = tmp_path / "state.db"

    with sqlite_checkpointer(db) as checkpointer:
        app = build_graph(checkpointer=checkpointer)
        r1 = app.invoke(_say("我想做一个记账 CLI"), _cfg("persist-t"))
        assert r1["task_brief"] == "我想做一个记账 CLI"
        r_choice = app.invoke(_say("下一步"), _cfg("persist-t"))
        assert r_choice["turn_end_reason"] == "choice:build_way"

    # 进程退出后重开：新 app 实例、同一 sqlite 库、同 thread——状态恢复续跑
    with sqlite_checkpointer(db) as checkpointer:
        app2 = build_graph(checkpointer=checkpointer)
        r2 = app2.invoke(_resolve(r_choice, "简化文档"), _cfg("persist-t"))
        assert r2["task_brief"] == "我想做一个记账 CLI"
        assert r2["build_way"] == "way3"
