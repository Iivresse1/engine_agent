"""ask_tasks_node（14 票瘦身）：task_brief 从首条人类消息写定 + round_end 收轮。

指引一问的发射与消费已移至 guidance_trigger_node（见 test_guidance_trigger.py）。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from project_agent.nodes import ask_tasks_node


def _state(**kw) -> dict:
    base = {"actor_messages": []}
    base.update(kw)
    return base


def test_01_legacy_session_with_task_brief_is_noop():
    """一次写定 + 01 遗留会话直达：task_brief 已设 → {}（可重入零副作用）。"""
    state = _state(task_brief="已有简报", actor_messages=[HumanMessage("闲聊")])
    assert ask_tasks_node(state) == {}


def test_task_brief_already_set_even_mid_question_returns_empty():
    """task_brief 已设时即便上轮是 question 续跑也 → {}（问答消费归 guidance_trigger）。"""
    state = _state(task_brief="x", turn_end_reason="question", guidance_pref=None)
    assert ask_tasks_node(state) == {}


def test_first_human_message_writes_brief_with_round_end():
    """首条人类消息（原始想法）写定简报 + round 断点收轮。"""
    state = _state(actor_messages=[HumanMessage("我想做个 2048 游戏")])
    updates = ask_tasks_node(state)
    assert updates["task_brief"] == "我想做个 2048 游戏"
    assert updates["turn_end_reason"] == "round"
    payload = updates["turn_end_payload"]
    assert "任务简报已记录" in payload["round_output"]
    assert "我想做个 2048 游戏" in payload["round_output"]
    assert payload["todo_board"] == []


def test_brief_from_first_human_message_not_latest():
    """多条消息：简报取首条人类消息（原始想法），非最新。"""
    state = _state(
        actor_messages=[
            HumanMessage("我想做个 2048 游戏"),
            AIMessage("好的"),
            HumanMessage("补充：要有排行榜"),
        ]
    )
    updates = ask_tasks_node(state)
    assert updates["task_brief"] == "我想做个 2048 游戏"
    assert "任务简报已记录：我想做个 2048 游戏" == updates["turn_end_payload"]["round_output"]


def test_no_question_breakpoint_ever_emitted():
    """14 票瘦身：ask_tasks 不再发任何 question 断点（首启只写简报）。"""
    state = _state(
        actor_messages=[HumanMessage("我想做个 2048 游戏")],
        turn_end_reason="question",  # 即便上轮 question 也只写简报
        guidance_pref=None,
        user_mode=None,
    )
    updates = ask_tasks_node(state)
    assert updates["turn_end_reason"] == "round"
    assert "question_text" not in updates.get("turn_end_payload", {})


def test_no_human_message_returns_empty():
    """无人类消息（空输入兜底）→ {}（不写简报不收轮）。"""
    state = _state(actor_messages=[AIMessage("只有 AI 消息")])
    assert ask_tasks_node(state) == {}


def test_whitespace_only_message_not_brief():
    """空白消息不算首条人类想法 → {}。"""
    state = _state(actor_messages=[HumanMessage("   ")])
    assert ask_tasks_node(state) == {}
