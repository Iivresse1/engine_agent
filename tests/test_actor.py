"""actor 节点工厂（05 票终裁 7）：模型调用、todos 勾选、隔离红线。

切片 3：assembler→actor→END 临时直连（verifier 切片 4 接入）；
model=None → 05 骨架 round_end，不调模型不产 AIMessage。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_actor_node
from project_agent.routing import CONTEXT_ASSEMBLER, entry_route
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]


def _cfg(thread: str = "t-actor") -> dict:
    return {"configurable": {"thread_id": thread}}


def _assembled(todos: list) -> dict:
    return {
        "system": "你是构建 agent。当前方式 way1，指引 off，待办 2 项",
        "todo_board": [f"pending: {t['content']}" for t in todos],
        "scope": "main",
    }


def test_entry_route_row4_uncleared_todos_to_context_assembler():
    assert entry_route({"task_brief": "x", "build_way": "way1", "todos": TWO_PENDING}) == CONTEXT_ASSEMBLER
    assert entry_route(
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [
                {"content": "a", "status": "completed"},
                {"content": "b", "status": "in_progress"},
            ],
        }
    ) == CONTEXT_ASSEMBLER


def test_entry_route_cleared_todos_still_planner_until_verifier_slice():
    """切片 3 阶段：todos 清暂回落 planner（行 5/7 切片 4 落位）。"""
    assert (
        entry_route(
            {
                "task_brief": "x",
                "build_way": "way1",
                "todos": [{"content": "a", "status": "completed"}],
            }
        )
        == "planner"
    )


def test_actor_model_none_writes_skeleton_round_end():
    node = make_actor_node(None)
    state = {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING)}
    updates = node(state, _cfg())
    assert updates["turn_end_reason"] == "round"
    assert "主环待真模型接入" in updates["turn_end_payload"]["round_output"]
    assert "actor_messages" not in updates  # 不产 AIMessage
    assert "todos" not in updates  # 无产出不勾选


def test_actor_calls_model_with_system_plus_actor_history():
    model = ScriptedModel(["回复甲"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [HumanMessage(content="你好"), AIMessage(content="旧回复")],
    }
    updates = node(state, _cfg("tid-9"))
    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["role"] == "actor"
    assert call["thread_id"] == "tid-9"
    assert call["messages"] == [
        {"role": "system", "content": "你是构建 agent。当前方式 way1，指引 off，待办 2 项"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "旧回复"},
    ]
    assert updates["actor_messages"] == [AIMessage(content="回复甲")]
    assert updates["turn_end_payload"]["round_output"] == "回复甲"


def test_actor_checks_todos_by_exact_completion_marker():
    """响应文本含 f"完成：{content}" 子串 → 置 completed；匹配不到跳过。"""
    model = ScriptedModel(["好的，完成：梳理需求边界，继续下一步。"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [HumanMessage(content="推进")],
    }
    updates = node(state, _cfg())
    assert [item["status"] for item in updates["todos"]] == ["completed", "pending"]
    # round_end 的 todo_board 用勾选后的板
    board = updates["turn_end_payload"]["todo_board"]
    assert board == ["completed: 梳理需求边界", "pending: 推进对话任务"]


def test_actor_todo_check_requires_exact_content():
    """精确匹配：响应只含近似文本（缺完整 content）不勾选。"""
    model = ScriptedModel(["完成：梳理需求"])  # 不是完整 content
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [],
    }
    updates = node(state, _cfg())
    assert [item["status"] for item in updates["todos"]] == ["pending", "pending"]


def test_actor_skips_completed_and_checks_in_progress():
    """completed 项不再处理；in_progress 项可勾。"""
    todos = [
        {"content": "梳理需求边界", "status": "completed"},
        {"content": "推进对话任务", "status": "in_progress"},
    ]
    model = ScriptedModel(["完成：推进对话任务"])
    node = make_actor_node(model)
    updates = node(
        {"todos": todos, "assembled_context": _assembled(todos), "actor_messages": []},
        _cfg(),
    )
    assert [item["status"] for item in updates["todos"]] == ["completed", "completed"]


def test_actor_isolation_redline_no_demo_history_in_model_calls():
    """验收 7：model.calls 的 messages 只含 system+actor 历史——demo 私有历史绝不出现。"""
    marker = "DEMO_PRIVATE_MARKER_XYZ"
    model = ScriptedModel(["回复"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [HumanMessage(content="主线输入")],
        "demo_messages": [HumanMessage(content=f"demo 私密 {marker}"), AIMessage(content=marker)],
    }
    node(state, _cfg())
    for call in model.calls:
        for message in call["messages"]:
            assert marker not in str(message.values())


def test_graph_assembler_actor_flow_with_model():
    """图级：todos 未清 → context_assembler → actor → END（切片 3 临时直连）。"""
    model = ScriptedModel(["完成：梳理需求边界。"])
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=model)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-actor-1"),
    )
    assert r["turn_end_reason"] == "round"
    assert r["turn_end_payload"]["round_output"] == "完成：梳理需求边界。"
    assert [item["status"] for item in r["todos"]] == ["completed", "pending"]
    assert r["assembled_context"]["scope"] == "main"
    assert len(model.calls) == 1


def test_graph_model_none_actor_skeleton_inert():
    """model=None：assembler→actor→END 不挂死，05 骨架 round_end。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-actor-2"),
    )
    assert r["turn_end_reason"] == "round"
    assert "主环待真模型接入" in r["turn_end_payload"]["round_output"]
    assert [item["status"] for item in r["todos"]] == ["pending", "pending"]


def test_graph_isolation_redline_seeded_demo_messages():
    """图级验收 7：seed demo_messages 带独特标记 → 绝不出现在任何 model 调用。"""
    marker = "DEMO_PRIVATE_MARKER_ABC"
    model = ScriptedModel(["回复乙"])
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=model)
    app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="主线")],
            "demo_messages": [HumanMessage(content=f"demo 侧 {marker}")],
        },
        _cfg("g-actor-3"),
    )
    assert model.calls
    for call in model.calls:
        for message in call["messages"]:
            assert marker not in str(message.values())
