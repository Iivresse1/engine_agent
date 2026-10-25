"""planner 节点：todos 计划与重规划（05 票终裁 5）。

测试断言结构非文案（条数/三态/计数语义）；way 模板内容不在断言范围。
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import planner_node


@pytest.mark.parametrize(
    ("way", "expected_items"),
    [
        ("way1", 2),
        ("way2", 2),
        ("way3", 4),
        ("way4", 3),
    ],
    ids=["way1", "way2", "way3", "way4"],
)
def test_planner_new_plan_each_way(way, expected_items):
    """新计划（todos 空）：模板条数、全 pending、计数清零、round 断点。"""
    state = {"task_brief": "做个工具", "build_way": way, "todos": []}
    updates = planner_node(state)
    todos = updates["todos"]
    assert len(todos) == expected_items
    assert all(item["status"] == "pending" for item in todos)
    assert all(isinstance(item["content"], str) and item["content"] for item in todos)
    assert updates["main_loop_count"] == 0
    assert updates["turn_end_reason"] == "round"
    assert (
        f"已列出 {expected_items} 项计划"
        in updates["turn_end_payload"]["round_output"]
    )
    board = updates["turn_end_payload"]["todo_board"]
    assert len(board) == expected_items
    assert all(line.startswith("pending: ") for line in board)


def test_planner_unknown_way_falls_back_to_single_item():
    """未知 way → 空 → 兜底单项『确认构建范围』。"""
    updates = planner_node({"task_brief": "x", "build_way": "way9", "todos": []})
    assert [item["content"] for item in updates["todos"]] == ["确认构建范围"]
    assert updates["todos"][0]["status"] == "pending"
    assert "已列出 1 项计划" in updates["turn_end_payload"]["round_output"]


def test_planner_replan_rewrites_all_pending_and_preserves_count():
    """重规划（todos 已设）：todos 全新 pending + main_loop_count 保留。"""
    state = {
        "task_brief": "x",
        "build_way": "way3",
        "todos": [{"content": "旧项", "status": "completed"}],
        "main_loop_count": 3,
    }
    updates = planner_node(state)
    assert len(updates["todos"]) == 4
    assert all(item["status"] == "pending" for item in updates["todos"])
    assert updates["main_loop_count"] == 3


@pytest.mark.parametrize("count", [5, 6], ids=["exactly5", "above5"])
def test_planner_replan_resets_count_when_exhausted(count):
    """重规划遇旧计数 >=5：清零开新循环（耗尽恢复路径）。"""
    state = {
        "task_brief": "x",
        "build_way": "way1",
        "todos": [{"content": "旧项", "status": "completed"}],
        "main_loop_count": count,
    }
    updates = planner_node(state)
    assert updates["main_loop_count"] == 0


def test_graph_routes_empty_todos_to_planner_round():
    """图级：todos 空 → START 路由 planner → planner→END 收轮。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_pref": "auto",
            "todos": [],
            "actor_messages": [],
        },
        {"configurable": {"thread_id": "planner-1"}},
    )
    assert r["turn_end_reason"] == "round"
    assert "已列出" in r["turn_end_payload"]["round_output"]
    assert len(r["todos"]) == 2
    assert r["main_loop_count"] == 0
