"""ask_tasks_node 跨轮问卷：首启四问 → 答案逐题落盘 → task_brief 从首条人类消息写定。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from project_agent.nodes import ask_tasks_node


def _state(**kw) -> dict:
    base = {"actor_messages": []}
    base.update(kw)
    return base


def _question_payload(question_text: str, options: list[str]) -> dict:
    return {"question_text": question_text, "options": options, "asker": "actor"}


def test_01_legacy_session_with_task_brief_skips_questionnaire():
    """一次写定 + 01 遗留会话直达：task_brief 已设 → {}。"""
    state = _state(task_brief="已有简报")
    assert ask_tasks_node(state) == {}


def test_first_entry_asks_q1_when_no_question_pending():
    """非 question 后续（首轮）：问第一题——用户想法绝不被当答案解释。"""
    state = _state(actor_messages=[HumanMessage("我想做个 2048 游戏")])
    updates = ask_tasks_node(state)
    assert updates["turn_end_reason"] == "question"
    payload = updates["turn_end_payload"]
    assert payload["question_text"] == "你的编程基础？"
    assert payload["options"] == ["有一定编程基础", "我不了解编程"]
    assert payload["asker"] == "actor"
    assert updates["awaiting_input_from"] == "actor"
    assert "task_brief" not in updates  # 想法不当答案也不写简报


def test_answer_to_pending_question_writes_field_then_asks_next():
    """上一轮 question 时最新人类消息=当前题答案：Q1 答案落盘 → 问 Q2。"""
    state = _state(
        actor_messages=[
            HumanMessage("我想做个 2048 游戏"),
            HumanMessage("我不了解编程"),
        ],
        turn_end_reason="question",
        user_mode=None,
    )
    updates = ask_tasks_node(state)
    assert updates["user_mode"] == "novice"
    assert updates["turn_end_reason"] == "question"
    # novice 落盘后问 Q2：问题文本追加 novice_hint
    assert (
        updates["turn_end_payload"]["question_text"] == "希望新手指引如何运作？；新手推荐 1"
    )
    assert updates["turn_end_payload"]["options"] == ["自动每轮", "每轮询问", "关"]


def test_novice_gets_hint_appended_on_q2():
    """user_mode==novice 时 Q2 问题文本追加 novice_hint。"""
    state = _state(
        actor_messages=[HumanMessage("零基础")],
        turn_end_reason="question",
        user_mode="novice",
        guidance_pref=None,
    )
    updates = ask_tasks_node(state)
    assert "新手推荐 1" in updates["turn_end_payload"]["question_text"]


def test_all_four_answered_writes_task_brief_from_first_human_message():
    """四问全齐：task_brief 从首条人类消息（原始想法）写定 + round_end。"""
    state = _state(
        actor_messages=[
            HumanMessage("我想做个 2048 游戏"),
            HumanMessage("我不了解编程"),
            HumanMessage("自动每轮"),
            HumanMessage("AI 自动审核"),
            HumanMessage("默认技能包"),
        ],
        turn_end_reason="question",
        user_mode="novice",
        guidance_pref="auto",
        decision_mode="ai_review",
        skill_packs=["default"],
    )
    updates = ask_tasks_node(state)
    assert updates["task_brief"] == "我想做个 2048 游戏"  # 首条，非最新
    assert updates["turn_end_reason"] == "round"
    assert "任务简报已记录" in updates["turn_end_payload"]["round_output"]


def test_uninterpretable_answer_reasks_same_question_idempotently():
    """答案不可解释 → 重问本题（幂等零副作用：不写字段不写简报）。"""
    state = _state(
        actor_messages=[
            HumanMessage("想法"),
            HumanMessage("嗯嗯嗯"),
        ],
        turn_end_reason="question",
    )
    updates = ask_tasks_node(state)
    assert updates["turn_end_reason"] == "question"
    assert updates["turn_end_payload"]["question_text"] == "你的编程基础？"
    for field in ("user_mode", "guidance_pref", "decision_mode", "skill_packs", "task_brief"):
        assert field not in updates


def test_skill_packs_empty_list_is_set_not_questioned():
    """skill_packs=[] 是合法已设值：前三个+Q4 已答（含空列表）→ 走简报写定路径。"""
    state = _state(
        actor_messages=[HumanMessage("我想做个游戏")],
        turn_end_reason="question",
        user_mode="experienced",
        guidance_pref="ask",
        decision_mode="manual",
        skill_packs=[],
    )
    updates = ask_tasks_node(state)
    # 全齐（skill_packs=[] 算已答）→ task_brief 写定
    assert updates["task_brief"] == "我想做个游戏"


def test_empty_string_answer_is_unset():
    """空串视同未设：下一题仍是当前字段。"""
    state = _state(turn_end_reason="question", user_mode="", guidance_pref=None)
    updates = ask_tasks_node(state)
    assert updates["turn_end_payload"]["question_text"] == "你的编程基础？"


def test_non_question_followup_asks_first_unset():
    """非 question 后续（round/choice 后重进 ask_tasks）：问第一未设题。"""
    state = _state(
        actor_messages=[HumanMessage("闲聊")],
        turn_end_reason="round",
        user_mode="novice",
        guidance_pref=None,  # 未设 → 问 Q2
    )
    updates = ask_tasks_node(state)
    # novice 且问的是 Q2 → 追加新手推荐提示
    assert updates["turn_end_payload"]["question_text"] == "希望新手指引如何运作？；新手推荐 1"
