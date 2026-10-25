"""05 票大回放：seed 直达 → planner 轮 → 工作轮 → 断点续跑 → 双过 END。

断言：每轮 turn_end_reason；todos 三态变化时序；todos_all_completed 时序；
main_loop_count 清而未过 ++；assembled_context 每轮覆写（内容随 todo 状态不同）；
round_summary 产出；隔离红线（demo 私有历史绝不出现在 model 调用）。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from tests.doubles.fake_model import ScriptedModel

pytestmark = pytest.mark.replay

DEMO_MARKER = "DEMO_PRIVATE_HISTORY_MARKER_42"


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def _cfg() -> dict:
    return {"configurable": {"thread_id": "main-loop-replay"}}


def test_main_loop_full_replay():
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            # 工作轮 1：actor 勾第一项；verifier false（未清）
            "完成：梳理需求边界。先对齐范围。",
            "task_complete: false",
            # 工作轮 2：actor 勾第二项；verifier true（双过）
            "完成：推进对话任务。本轮交付完成。",
            "task_complete: true",
        ]
    )
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg()

    # seed：invoke 输入带 task_brief/build_way=way1/问卷四字段直达 → planner 轮
    r0 = app.invoke(
        {
            "task_brief": "做个记账 CLI",
            "build_way": "way1",
            "user_mode": "experienced",
            "guidance_pref": "off",
            "decision_mode": "manual",
            "skill_packs": [],
            "actor_messages": [HumanMessage(content="我想做记账工具")],
        },
        cfg,
    )
    assert r0["turn_end_reason"] == "round"  # planner 轮
    assert "已列出" in r0["turn_end_payload"]["round_output"]
    assert [item["status"] for item in r0["todos"]] == ["pending", "pending"]
    assert r0["main_loop_count"] == 0
    assert len(model.calls) == 0  # planner 不耗模型出牌

    # 工作轮 1：actor 勾第一项 → verifier false（未清）→ END round 断点
    r1 = app.invoke(_say("开始吧"), cfg)
    assert r1["turn_end_reason"] == "round"
    assert r1["turn_end_payload"]["round_output"] == "完成：梳理需求边界。先对齐范围。"
    assert [item["status"] for item in r1["todos"]] == ["completed", "pending"]
    assert r1["todos_all_completed"] is False
    assert r1["task_complete"] is False
    assert "main_loop_count" not in r1 or r1["main_loop_count"] == 0  # 未清不自增
    # round_summary 产出（actor 末尾工序）
    assert r1["round_summary"] == "完成：梳理需求边界。先对齐范围。"
    # assembled_context 每轮覆写：本轮待办 2 项
    assert "待办 2 项" in r1["assembled_context"]["system"]
    ctx1 = r1["assembled_context"]

    # 下条输入融合进 actor_messages → 工作轮 2
    r2 = app.invoke(_say("继续推进"), cfg)
    assert r2["turn_end_reason"] == "round"
    assert [item["status"] for item in r2["todos"]] == ["completed", "completed"]
    assert r2["todos_all_completed"] is True
    assert r2["task_complete"] is True
    assert r2["is_docs_finished"] is True
    assert "main_loop_count" not in r2 or r2["main_loop_count"] == 0
    assert r2["round_summary"] == "完成：推进对话任务。本轮交付完成。"
    # assembled_context 覆写：两轮内容随 todo 状态不同（2 项→1 项）
    assert "待办 1 项" in r2["assembled_context"]["system"]
    assert ctx1["system"] != r2["assembled_context"]["system"]
    assert ctx1["todo_board"] != r2["assembled_context"]["todo_board"]

    # 模型调用序：actor, verifier, actor, verifier——角色与消息形态
    assert [c["role"] for c in model.calls] == [
        "actor",
        "verifier",
        "actor",
        "verifier",
    ]
    # 隔离红线：actor 调用 messages 只含 system+actor 历史（本回放无 demo seed，
    # 断言消息形态收紧）
    for call in model.calls:
        roles_seen = [m["role"] for m in call["messages"]]
        if call["role"] == "actor":
            assert roles_seen[0] == "system"
            assert all(r in ("user", "assistant") for r in roles_seen[1:])
    # verifier prompt 含任务简报与 todo 三态板
    v2 = model.calls[3]["messages"][-1]["content"]
    assert "做个记账 CLI" in v2
    assert "completed: 推进对话任务" in v2


def test_main_loop_cleared_unpassed_count_increments_then_replans():
    """清而未过时序：actor 全勾 → verifier false → count++ → 同轮 planner 重规划。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "完成：梳理需求边界。完成：推进对话任务。",
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model)
    cfg = {"configurable": {"thread_id": "cleared-unpassed"}}

    r0 = app.invoke(
        {
            "task_brief": "x",
            "build_way": "way1",
            "actor_messages": [HumanMessage(content="seed")],
        },
        cfg,
    )
    assert r0["turn_end_reason"] == "round"
    assert r0["main_loop_count"] == 0

    r1 = app.invoke(_say("干完它"), cfg)
    # 同轮：actor 勾全 → verifier false（count 0→1）→ planner 重规划（count 保留 <5）
    assert r1["turn_end_reason"] == "round"
    assert "已列出" in r1["turn_end_payload"]["round_output"]
    assert r1["main_loop_count"] == 1
    assert r1["todos_all_completed"] is True  # verifier 扫描时点
    assert [item["status"] for item in r1["todos"]] == ["pending", "pending"]  # 重规划板


def test_main_loop_isolation_redline_with_demo_seed():
    """隔离红线（验收 7）：seed demo_messages 带独特标记 → 绝不出现在任何 model 调用。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "完成：梳理需求边界。",
            "task_complete: false",
            "完成：推进对话任务。",
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model)
    cfg = {"configurable": {"thread_id": "redline"}}

    r0 = app.invoke(
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [
                {"content": "梳理需求边界", "status": "pending"},
                {"content": "推进对话任务", "status": "pending"},
            ],
            "actor_messages": [HumanMessage(content="主线输入")],
            "demo_messages": [HumanMessage(content=f"demo 私语 {DEMO_MARKER}")],
        },
        cfg,
    )
    assert r0["turn_end_reason"] == "round"
    assert model.calls  # 有调用才谈得上隔离
    for call in model.calls:
        for message in call["messages"]:
            assert DEMO_MARKER not in str(message.values())
    # 融合通道也不把 demo 历史混入主线
    r1 = app.invoke(_say("下一步"), cfg)
    for call in model.calls:
        for message in call["messages"]:
            assert DEMO_MARKER not in str(message.values())
