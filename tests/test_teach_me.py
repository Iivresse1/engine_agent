"""13 票 teach-me：四选解释引擎 + run_teach_me 落盘三件 + actor 起手决议路径。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from project_agent.nodes import make_actor_node
from project_agent.shared_docs import SharedDocs
from project_agent.teach_me import (
    GUIDANCE_OPTIONS,
    interpret_teach_choice,
    run_teach_me,
)
from tests.doubles.fake_model import ScriptedModel


def _cfg(thread: str = "t-teach") -> dict:
    return {"configurable": {"thread_id": thread}}


def _guidance_state() -> dict:
    """上轮 question（指引询问）后的 actor 入参态。"""
    return {
        "build_way": "way2",
        "task_brief": "记账 CLI",
        "guidance_mode": "ask",
        "todos": [],
        "assembled_context": {"system": "你是构建 agent。", "todo_board": [], "scope": "main"},
        "actor_messages": [
            HumanMessage(content="构建方式已定"),
            AIMessage(content="本轮产出"),
            HumanMessage(content="深度教学"),
        ],
        "turn_end_reason": "question",
        "round_count": 2,
        "round_summary": "本轮产出",
    }


# ---------- 四选解释引擎 ----------


def test_interpret_teach_choice_variants():
    assert interpret_teach_choice("1") == "brief"
    assert interpret_teach_choice("2") == "teach"
    assert interpret_teach_choice("3") == "skip"
    assert interpret_teach_choice("4") == "teach_always"
    assert interpret_teach_choice("简短讲解") == "brief"
    assert interpret_teach_choice("深度教学") == "teach"
    assert interpret_teach_choice("跳过") == "skip"
    assert interpret_teach_choice("以后都深度教学") == "teach_always"
    # 长选项原文整串可解释
    assert interpret_teach_choice(GUIDANCE_OPTIONS[1]) == "teach"
    assert interpret_teach_choice(GUIDANCE_OPTIONS[3]) == "teach_always"
    # 解释不了
    assert interpret_teach_choice("嗯") is None
    assert interpret_teach_choice("") is None
    assert interpret_teach_choice(None) is None


# ---------- run_teach_me：三件落盘 ----------


def test_run_teach_me_writes_three_artifacts(tmp_path):
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["<html><input type=checkbox>概念A</html>"])
    receipt = run_teach_me(
        model,
        docs,
        {"user_mode": "novice", "guidance_pref": "ask", "build_way": "way2", "task_brief": "记账 CLI"},
        round_no=1,
        round_summary="本轮产出",
        doc_slice="【R1】文档",
        thread_id="t1",
    )
    assert receipt == "教学页已生成：teach-me/R1/index.html"
    page = (tmp_path / "teach-me" / "R1" / "index.html").read_text(encoding="utf-8")
    assert page.startswith("<html>")
    profile = (tmp_path / "teach-me" / "learner-profile.md").read_text(encoding="utf-8")
    assert "编程基础：novice" in profile
    session = (tmp_path / "teach-me" / "session.md").read_text(encoding="utf-8")
    assert "R1" in session and "概念清单 1 项" in session
    # 隔离红线：role=ask_agent 单发
    call = model.calls[0]
    assert call["role"] == "ask_agent"
    material = call["messages"][0]["content"]
    assert "页面式深度教学" in material  # skill body
    assert "本轮产出" in material  # round_summary
    assert "【R1】文档" in material  # doc_slice


def test_run_teach_me_second_call_reads_session(tmp_path):
    """第二次生成：画像不重写、session 追加、prompt 含既往日志（不重教）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["<html>一</html>", "<html><input type=checkbox>二</html>"])
    state = {"user_mode": "experienced", "build_way": "way2", "task_brief": "x"}
    run_teach_me(model, docs, state, round_no=1, round_summary="s1", doc_slice="", thread_id="t")
    profile_before = (tmp_path / "teach-me" / "learner-profile.md").read_text(encoding="utf-8")
    run_teach_me(model, docs, state, round_no=2, round_summary="s2", doc_slice="", thread_id="t")
    profile_after = (tmp_path / "teach-me" / "learner-profile.md").read_text(encoding="utf-8")
    assert profile_before == profile_after  # 幂等：画像只首启写
    session = (tmp_path / "teach-me" / "session.md").read_text(encoding="utf-8")
    assert "R1" in session and "R2" in session
    second_material = model.calls[1]["messages"][0]["content"]
    assert "既往教学日志" in second_material
    assert "已掌握的概念不要重教" in second_material


def test_run_teach_me_empty_html_no_artifacts(tmp_path):
    docs = SharedDocs(tmp_path)
    model = ScriptedModel([""])
    receipt = run_teach_me(
        model, docs, {"task_brief": "x"}, round_no=1, round_summary="s", doc_slice="", thread_id="t"
    )
    assert "失败" in receipt
    assert not (tmp_path / "teach-me" / "R1").exists()
    assert not (tmp_path / "teach-me" / "session.md").exists()


# ---------- actor 起手决议路径 ----------


def test_actor_start_interprets_teach_choice_teach(tmp_path):
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["<html>教学页</html>"])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(_guidance_state(), _cfg())
    assert updates["turn_end_reason"] == "round"
    assert "教学页已生成：teach-me/R2/index.html" in updates["turn_end_payload"]["round_output"]
    assert "teach_me_pref" not in updates  # 单轮 teach 不写 always


def test_actor_start_interprets_teach_always_writes_pref(tmp_path):
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["<html>教学页</html>"])
    node = make_actor_node(model, shared_docs=docs)
    state = _guidance_state()
    state["actor_messages"][-1] = HumanMessage(content="以后都深度教学")
    updates = node(state, _cfg())
    assert updates["teach_me_pref"] == "always"
    assert "教学页已生成" in updates["turn_end_payload"]["round_output"]


def test_actor_start_interprets_skip_returns_notice(tmp_path):
    docs = SharedDocs(tmp_path)
    model = ScriptedModel([])
    node = make_actor_node(model, shared_docs=docs)
    state = _guidance_state()
    state["actor_messages"][-1] = HumanMessage(content="跳过")
    updates = node(state, _cfg())
    assert updates["turn_end_reason"] == "round"
    assert "跳过讲解" in updates["turn_end_payload"]["round_output"]
    assert model.calls == []


def test_actor_start_uninterpretable_reasks_question(tmp_path):
    """不可解释 → 重发同一 question 断点（幂等零副作用）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel([])
    node = make_actor_node(model, shared_docs=docs)
    state = _guidance_state()
    state["actor_messages"][-1] = HumanMessage(content="嗯")
    updates = node(state, _cfg())
    assert updates["turn_end_reason"] == "question"
    assert updates["turn_end_payload"]["options"] == GUIDANCE_OPTIONS
    assert model.calls == []


def test_actor_start_brief_falls_through_to_body(tmp_path):
    """选"简短讲解"→ 落回正常身体（本轮普通产出 + 普通指引路径）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["正常产出", "指引文本"])
    node = make_actor_node(model, shared_docs=docs)
    state = _guidance_state()
    state["actor_messages"][-1] = HumanMessage(content="简短讲解")
    state["notes_version"] = 2
    state["guidance_read_version"] = 0
    updates = node(state, _cfg())
    assert updates["turn_end_reason"] == "round"
    assert updates["turn_end_payload"]["round_output"].endswith("指引文本")
