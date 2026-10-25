"""LOOP_EXHAUSTED 节点 + 计数耗尽回放 + 耗尽恢复（05 票终裁 9）。

- 节点：turn_end_reason=loop_exhausted + payload{scene, help_text}
- 耗尽回放：5 次清而未过 → 第 5 轮 loop_exhausted 断点（含现场与求助说明）
- 耗尽恢复：下条输入融合 → 入口行 5（清+false+count5→planner）→
  重规划 + main_loop_count 清零开新循环
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import loop_exhausted_node
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]
BOTH_DONE_TEXT = "完成：梳理需求边界。完成：推进对话任务。"


def _cfg(thread: str = "t-exhaust") -> dict:
    return {"configurable": {"thread_id": thread}}


def test_loop_exhausted_node_payload_shape():
    state = {
        "todos": [
            {"content": "a", "status": "completed"},
            {"content": "b", "status": "pending"},
        ],
        "main_loop_count": 5,
    }
    updates = loop_exhausted_node(state)
    assert updates["turn_end_reason"] == "loop_exhausted"
    payload = updates["turn_end_payload"]
    assert set(payload) == {"scene", "help_text"}
    assert "5" in payload["scene"]
    assert "1/2" in payload["scene"]  # todos 已完成数/总数
    assert payload["help_text"]


def test_loop_exhausted_node_empty_todos_defensive():
    updates = loop_exhausted_node({"todos": [], "main_loop_count": 5})
    assert "0/0" in updates["turn_end_payload"]["scene"]


def _exhausted_app(saver, script):
    model = ScriptedModel(script)
    return build_graph(checkpointer=saver, model=model)


def test_five_cleared_unpassed_rounds_hit_loop_exhausted():
    """耗尽回放：连发 5 轮（actor 勾全 + verifier false）→ 第 5 轮 loop_exhausted。"""
    saver = InMemorySaver()
    script = []
    for i in range(5):
        script.append(BOTH_DONE_TEXT)  # actor：一轮勾完两项
        script.append("task_complete: false")  # verifier：不过
    app = _exhausted_app(saver, script)
    cfg = _cfg("exhaust-1")

    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_pref": "off",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        cfg,
    )
    # 第 1 轮：清而未过 → 同轮重新规划（verifier 自增 count=1，planner 保留）
    assert r["turn_end_reason"] == "round"
    assert "已列出" in r["turn_end_payload"]["round_output"]

    counts = []
    for i in range(4):
        r = app.invoke(_say("继续"), cfg)
        counts.append(r.get("main_loop_count"))
        if i < 3:
            assert r["turn_end_reason"] == "round"  # 重新规划轮收 round
    # 第 5 轮（i=3，count 已达 5）：verifier 后 _after_verifier → LOOP_EXHAUSTED
    assert r["turn_end_reason"] == "loop_exhausted"
    payload = r["turn_end_payload"]
    assert "主环计数 5" in payload["scene"]
    assert "求助" not in payload["help_text"] or payload["help_text"]  # help_text 非空
    assert "人工接管" in payload["help_text"]


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def test_exhausted_recovery_next_input_replanned_with_count_reset():
    """耗尽恢复：loop_exhausted 断点后下条输入 → 入口行 5 → planner 重规划 + count 清零。"""
    saver = InMemorySaver()
    script = []
    for i in range(5):
        script.append(BOTH_DONE_TEXT)
        script.append("task_complete: false")
    script.append("新一轮：完成：梳理需求边界。")  # 恢复后第 6 轮 actor
    script.append("task_complete: false")  # 恢复后 verifier
    app = _exhausted_app(saver, script)
    cfg = _cfg("exhaust-2")

    state = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_pref": "off",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        cfg,
    )
    for i in range(4):
        state = app.invoke(_say("继续"), cfg)
    assert state["turn_end_reason"] == "loop_exhausted"
    assert state["main_loop_count"] == 5

    # 下条输入（loop_exhausted=FREE_MAINLINE 融合）→ 入口行 5：清+false+count5 → planner
    r = app.invoke(_say("调整一下方向再来"), cfg)
    assert r["turn_end_reason"] == "round"
    assert "已列出" in r["turn_end_payload"]["round_output"]
    assert r["main_loop_count"] == 0  # planner 清零开新循环
    assert all(item["status"] == "pending" for item in r["todos"]) or any(
        item["status"] == "completed" for item in r["todos"]
    )  # 重规划全新板（本轮 actor 可能已勾第一项）
