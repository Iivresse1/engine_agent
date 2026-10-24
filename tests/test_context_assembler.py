"""context_assembler 节点：写 assembled_context（05 票终裁 6）。

每轮整覆写（state key 无 reducer）；不写任何消息；暂不入图（切片 3 接线）。
"""

from __future__ import annotations

from project_agent.nodes import context_assembler_node


def test_assembler_overwrites_full_context():
    state = {
        "task_brief": "x",
        "build_way": "way1",
        "guidance_mode": "auto",
        "current_scope": "src",
        "todos": [
            {"content": "梳理需求边界", "status": "completed"},
            {"content": "推进对话任务", "status": "in_progress"},
        ],
        "assembled_context": {"system": "旧值", "todo_board": ["旧板"], "scope": "旧"},
    }
    updates = context_assembler_node(state)
    assert set(updates) == {"assembled_context"}
    ctx = updates["assembled_context"]
    assert set(ctx) == {"system", "todo_board", "scope"}
    # 整覆写：旧值全灭
    assert ctx != state["assembled_context"]
    assert "way1" in ctx["system"]
    assert "auto" in ctx["system"]
    assert "1" in ctx["system"]  # 待办 1 项（未清数：in_progress 计未清）
    assert ctx["todo_board"] == ["completed: 梳理需求边界", "in_progress: 推进对话任务"]
    assert ctx["scope"] == "src"


def test_assembler_scope_defaults_to_main():
    updates = context_assembler_node({"build_way": "way1", "todos": []})
    assert updates["assembled_context"]["scope"] == "main"


def test_assembler_system_mentions_pending_count_only():
    state = {
        "build_way": "way3",
        "guidance_mode": "off",
        "todos": [
            {"content": "a", "status": "completed"},
            {"content": "b", "status": "completed"},
            {"content": "c", "status": "pending"},
        ],
    }
    ctx = context_assembler_node(state)["assembled_context"]
    assert "1" in ctx["system"]  # 未清 1 项
    assert ctx["todo_board"] == ["completed: a", "completed: b", "pending: c"]


def test_assembler_writes_no_messages():
    updates = context_assembler_node({})
    assert "actor_messages" not in updates
    assert "demo_messages" not in updates


def test_assembler_empty_todos_render_empty_board():
    ctx = context_assembler_node({"build_way": "way1"})["assembled_context"]
    assert ctx["todo_board"] == []
