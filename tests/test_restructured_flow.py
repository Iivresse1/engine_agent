"""14 票问卷重编排：简报直写 + 指引一问断点流 + user_mode 推导（图级回放）。"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph

pytestmark = pytest.mark.replay


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def _cfg(thread: str = "t-re14") -> dict:
    return {"configurable": {"thread_id": thread}}


def test_first_input_writes_brief_no_question():
    """首条自由文本 → 简报直写 round（零 question——四问已删）。"""
    app = build_graph(checkpointer=InMemorySaver())
    r = app.invoke(_say("我想做一个记账 CLI"), _cfg())
    assert r["turn_end_reason"] == "round"
    assert r["task_brief"] == "我想做一个记账 CLI"
    assert "任务简报已记录" in r["turn_end_payload"]["round_output"]


def test_build_ways_then_guidance_question_sequence():
    """序列：简报 round → choice → 决议 → 指引一问 question → 答案推导。"""
    app = build_graph(checkpointer=InMemorySaver())
    cfg = _cfg("t-seq")

    r = app.invoke(_say("做个坦克大战游戏"), cfg)
    assert r["turn_end_reason"] == "round"  # 简报
    r = app.invoke(_say("嗯"), cfg)
    assert r["turn_end_reason"] == "choice:build_way"  # 方式断点
    r = app.invoke({"resolution_inputs": ["2"]}, cfg)  # 决议 way2
    assert r["build_way"] == "way2"
    assert r["turn_end_reason"] == "question"  # 指引一问（14 票新相位）
    payload = r["turn_end_payload"]
    assert "需要每轮给出指引" in payload["question_text"]
    assert payload["options"][0].startswith("需要 —— ")
    assert payload["asker"] == "actor"

    r = app.invoke(_say("需要"), cfg)  # 指引答案
    assert r["guidance_pref"] == "auto"
    assert r["user_mode"] == "novice"  # 推导：要讲解→新手语境
    assert r["guidance_mode"] == "auto"
    assert r["turn_end_reason"] == "round"
    assert "指引偏好已记录" in r["turn_end_payload"]["round_output"]


def test_guidance_answer_off_derives_experienced():
    """答"不需要" → user_mode=experienced + guidance_mode=off。"""
    app = build_graph(checkpointer=InMemorySaver())
    cfg = _cfg("t-off")
    app.invoke(_say("做个游戏"), cfg)
    app.invoke(_say("嗯"), cfg)
    r = app.invoke({"resolution_inputs": ["1"]}, cfg)  # way1 决议 → 指引一问
    assert r["turn_end_reason"] == "question"
    r = app.invoke(_say("不需要"), cfg)
    assert r["guidance_pref"] == "off"
    assert r["user_mode"] == "experienced"
    assert r["guidance_mode"] == "off"  # way1 映射也 off（双保险）


def test_guidance_uninterpretable_reasks():
    """不可解释 → 重发同一 question（幂等零副作用）。"""
    app = build_graph(checkpointer=InMemorySaver())
    cfg = _cfg("t-reask")
    app.invoke(_say("做个游戏"), cfg)
    app.invoke(_say("嗯"), cfg)
    r = app.invoke({"resolution_inputs": ["2"]}, cfg)
    assert r["turn_end_reason"] == "question"
    r = app.invoke(_say("嗯嗯嗯"), cfg)  # 不可解释
    assert r["turn_end_reason"] == "question"
    assert "需要每轮给出指引" in r["turn_end_payload"]["question_text"]


def test_way4_proposals_waits_for_guidance():
    """way4 决议后先指引一问（新行优先于 PROPOSALS）——答完才进三方案。"""
    app = build_graph(checkpointer=InMemorySaver())
    cfg = _cfg("t-w4")
    app.invoke(_say("做个编译器"), cfg)
    app.invoke(_say("嗯"), cfg)
    r = app.invoke({"resolution_inputs": ["4"]}, cfg)  # way4 决议
    assert r["build_way"] == "way4"
    assert r["turn_end_reason"] == "question"  # 指引一问，不是 choice:proposal
    r = app.invoke(_say("先问我"), cfg)  # ask
    assert r["guidance_pref"] == "ask"
    assert r["guidance_mode"] == "ask"
    r = app.invoke(_say("继续"), cfg)  # 下一轮才进 PROPOSALS
    assert r["turn_end_reason"] == "choice:proposal"


def test_guidance_pref_set_skips_question():
    """guidance_pref 已设（种子/续跑）→ 跳过一问直达 planner（旧路径兼容）。"""
    app = build_graph(checkpointer=InMemorySaver())
    cfg = _cfg("t-skip")
    r = app.invoke(
        {
            "actor_messages": [HumanMessage(content="做个工具")],
            "guidance_pref": "off",
            "user_mode": "experienced",
        },
        cfg,
    )
    assert r["task_brief"] == "做个工具"
    r = app.invoke(_say("嗯"), cfg)
    assert r["turn_end_reason"] == "choice:build_way"
    r = app.invoke({"resolution_inputs": ["2"]}, cfg)
    # 指引已设 → 纯映射收轮（round），不再发 question
    assert r["guidance_mode"] == "off"
    assert r["turn_end_reason"] == "round"
