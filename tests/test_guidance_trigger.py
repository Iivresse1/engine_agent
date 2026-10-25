"""guidance_trigger 节点（14 票重编排）：指引一问的发射与消费 + 三态映射。

- 未设 且 简报/方式已齐 → 发 question 断点（指引一问，asker=actor）
- 上轮 question + 答案 → 写 guidance_pref/user_mode（推导）/guidance_mode + round_end
- guidance_pref 已设 → 纯映射写 guidance_mode（02 票既有路径）
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import guidance_trigger_node
from project_agent.routing import GUIDANCE_TRIGGER

_GUIDANCE_QUESTION_TEXT = "需要每轮给出指引帮助更好的理解项目吗 —— 构建时配讲解"
_GUIDANCE_OPTIONS = [
    "需要 —— 每轮自动附一段讲解",
    "先问我 —— 讲不讲当场决定",
    "不需要 —— 我自己看得懂",
]


# ---------- 状态 1：未设 + 简报/方式齐 → question 断点 ----------


def test_unset_with_brief_and_way_emits_question():
    state = {"task_brief": "想法", "build_way": "way2"}
    updates = guidance_trigger_node(state)
    assert updates["turn_end_reason"] == "question"
    payload = updates["turn_end_payload"]
    assert payload["question_text"] == _GUIDANCE_QUESTION_TEXT
    assert payload["explanation"] == "讲解会说明每轮为什么这么做、涉及哪些技术，边构建边学"
    assert payload["options"] == _GUIDANCE_OPTIONS
    assert payload["asker"] == "actor"
    assert updates["awaiting_input_from"] == "actor"
    for field in ("guidance_pref", "user_mode", "guidance_mode"):
        assert field not in updates


def test_unset_before_question_continuation_still_asks():
    """turn_end_reason 非 question（如 choice 决议轮）→ 仍发指引一问。"""
    state = {"task_brief": "想法", "build_way": "way3", "turn_end_reason": "round"}
    updates = guidance_trigger_node(state)
    assert updates["turn_end_reason"] == "question"
    assert updates["turn_end_payload"]["question_text"] == _GUIDANCE_QUESTION_TEXT


def test_phase_not_reached_falls_back_to_mapping():
    """简报/方式未齐（相位未达）：只写映射兜底，不发问。"""
    updates = guidance_trigger_node({"task_brief": "想法"})
    assert updates == {"guidance_mode": "off"}
    assert guidance_trigger_node({}) == {"guidance_mode": "off"}


# ---------- 状态 2：上轮 question + 答案 → 落盘三字段 + round_end ----------


def _answered_state(answer: str, build_way: str = "way2") -> dict:
    return {
        "task_brief": "想法",
        "build_way": build_way,
        "turn_end_reason": "question",
        "actor_messages": [HumanMessage("我想做个游戏"), HumanMessage(answer)],
    }


def test_answer_auto_writes_pref_user_mode_and_round_end():
    updates = guidance_trigger_node(_answered_state("需要"))
    assert updates["guidance_pref"] == "auto"
    assert updates["user_mode"] == "novice"  # auto/ask → novice 推导
    assert updates["guidance_mode"] == "auto"
    assert updates["turn_end_reason"] == "round"
    assert "指引偏好已记录" in updates["turn_end_payload"]["round_output"]


def test_answer_ask_writes_pref_user_mode_and_round_end():
    updates = guidance_trigger_node(_answered_state("先问"))
    assert updates["guidance_pref"] == "ask"
    assert updates["user_mode"] == "novice"
    assert updates["guidance_mode"] == "ask"


def test_answer_off_writes_pref_and_experienced_user_mode():
    updates = guidance_trigger_node(_answered_state("不用"))
    assert updates["guidance_pref"] == "off"
    assert updates["user_mode"] == "experienced"  # off → experienced 推导
    assert updates["guidance_mode"] == "off"


def test_answer_off_with_way1_maps_off():
    updates = guidance_trigger_node(_answered_state("看得懂", build_way="way1"))
    assert updates["guidance_pref"] == "off"
    assert updates["guidance_mode"] == "off"


def test_answer_takes_latest_human_message():
    """答案取最新人类消息（非首条）。"""
    state = {
        "task_brief": "想法",
        "build_way": "way2",
        "turn_end_reason": "question",
        "actor_messages": [
            HumanMessage("我想做个游戏"),
            AIMessage("指引一问"),
            HumanMessage("1"),  # 序号 1 → auto
        ],
    }
    updates = guidance_trigger_node(state)
    assert updates["guidance_pref"] == "auto"
    assert updates["user_mode"] == "novice"


def test_uninterpretable_answer_reasks_same_question():
    """答案不可解释 → 重发同一 question（幂等零副作用）。"""
    updates = guidance_trigger_node(_answered_state("嗯嗯嗯"))
    assert updates["turn_end_reason"] == "question"
    assert updates["turn_end_payload"]["question_text"] == _GUIDANCE_QUESTION_TEXT
    for field in ("guidance_pref", "user_mode"):
        assert field not in updates


def test_no_human_answer_after_question_reasks():
    """上轮 question 但无人类消息（空输入兜底）→ 重发。"""
    state = {"task_brief": "想法", "build_way": "way2", "turn_end_reason": "question"}
    updates = guidance_trigger_node(state)
    assert updates["turn_end_reason"] == "question"
    assert updates["turn_end_payload"]["question_text"] == _GUIDANCE_QUESTION_TEXT


# ---------- 状态 3：guidance_pref 已设 → 纯映射（02 票既有路径） ----------


def test_guidance_trigger_node_writes_guidance_mode_only():
    """spec 节点表：只写 guidance_mode，不写 turn_end。"""
    state = {"build_way": "way2", "guidance_pref": "ask", "user_mode": "novice"}
    updates = guidance_trigger_node(state)
    assert updates == {"guidance_mode": "ask"}


def test_guidance_trigger_node_way1_off():
    updates = guidance_trigger_node(
        {"build_way": "way1", "guidance_pref": "auto", "user_mode": "novice"}
    )
    assert updates == {"guidance_mode": "off"}


def test_guidance_trigger_constant_wired():
    assert GUIDANCE_TRIGGER == "guidance_trigger"


# ---------- 图级：build_ways 决议 → 指引一问 → 答案落盘 ----------


def test_graph_build_ways_resolution_then_guidance_question_then_answer():
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "gt-flow"}}

    # 轮 1：build_ways 决议（way3）→ 同轮接 guidance_trigger 发指引一问
    r1 = app.invoke({"task_brief": "想法", "resolution_inputs": ["用简化文档"]}, cfg)
    assert r1["build_way"] == "way3"
    assert r1["turn_end_reason"] == "question"
    assert r1["turn_end_payload"]["question_text"] == _GUIDANCE_QUESTION_TEXT
    assert r1["turn_end_payload"]["options"] == _GUIDANCE_OPTIONS
    assert "guidance_pref" not in r1 or not r1["guidance_pref"]

    # 轮 2：答案 "需要" → 三字段落盘 + round_end 收轮
    r2 = app.invoke({"actor_messages": [HumanMessage("需要")]}, cfg)
    assert r2["guidance_pref"] == "auto"
    assert r2["user_mode"] == "novice"
    assert r2["guidance_mode"] == "auto"
    assert r2["turn_end_reason"] == "round"
    assert "指引偏好已记录" in r2["turn_end_payload"]["round_output"]


def test_graph_guidance_question_reasked_on_uninterpretable_answer():
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "gt-reask"}}

    r1 = app.invoke({"task_brief": "想法", "resolution_inputs": ["对话"]}, cfg)
    assert r1["build_way"] == "way1"
    assert r1["turn_end_reason"] == "question"

    # 不可解释答案 → 重发同一问
    r2 = app.invoke({"actor_messages": [HumanMessage("嗯嗯")]}, cfg)
    assert r2["turn_end_reason"] == "question"
    assert r2["turn_end_payload"]["question_text"] == _GUIDANCE_QUESTION_TEXT

    # 合法答案后落盘（way1 → guidance_mode off）
    r3 = app.invoke({"actor_messages": [HumanMessage("1")]}, cfg)
    assert r3["guidance_pref"] == "auto"
    assert r3["user_mode"] == "novice"
    assert r3["guidance_mode"] == "off"  # way1 纯对话无构建轮可指引
    assert r3["turn_end_reason"] == "round"


def test_graph_guidance_mode_via_preferences():
    """pref 已设（旧路径）：build_ways 决议 → guidance_trigger 纯映射落盘。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "gt2"}}

    r = app.invoke(
        {
            "task_brief": "想法",
            "user_mode": "novice",
            "guidance_pref": "auto",
            "resolution_inputs": ["2"],
        },
        cfg,
    )
    assert r["build_way"] == "way2"
    assert r["guidance_mode"] == "auto"  # pref 优先
