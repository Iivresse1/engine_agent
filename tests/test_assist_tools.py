"""AskUserQuestion / SkillRecommend 工具本体（17 票补，清两条欠账）。"""

from __future__ import annotations

import pathlib

import pytest

from project_agent.assist_tools import (
    QuestionRequest,
    ask_user_question,
    recommend_skills,
    render_skill_recommendations,
)
from project_agent.model_client import ModelResult, ToolAwareResult, ToolCall
from project_agent.nodes import _actor_tool_runner, make_actor_node
from project_agent.skills import DEFAULT_PACK

# ---- AskUserQuestion ----

def test_ask_user_question_builds_structured_request() -> None:
    request = ask_user_question(
        "要哪种构建方式 —— 决定流程重量",
        "影响文档产出量",
        ["对话 —— 不产出文档", "完整文档 —— 六件"],
    )
    assert isinstance(request, QuestionRequest)
    assert request.text == "要哪种构建方式 —— 决定流程重量"
    assert request.explanation == "影响文档产出量"
    assert len(request.options) == 2


def test_ask_user_question_payload_matches_protocol_shape() -> None:
    """payload 形状必须与断点协议表逐字对齐（否则 validate_payload 会拒）。"""
    from project_agent.protocol import (
        BREAKPOINT_PROTOCOL,
        RoundEndReason,
        validate_payload,
    )

    payload = ask_user_question("问题主体", "解释", ["选项A"]).to_payload()
    required = set(BREAKPOINT_PROTOCOL[RoundEndReason.QUESTION].required_payload_fields)
    assert set(payload) == required
    assert validate_payload(RoundEndReason.QUESTION, payload) == payload


def test_ask_user_question_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        ask_user_question("   ")


def test_ask_user_question_defaults_explanation() -> None:
    request = ask_user_question("问题")
    assert request.explanation  # 非空（可读性契约：explanation 必填）


def test_ask_user_question_strips_blank_options() -> None:
    request = ask_user_question("问题", options=["a", "  ", "", "b"])
    assert request.options == ("a", "b")


# ---- SkillRecommend ----

def test_recommend_skills_returns_name_liner_reason() -> None:
    items = recommend_skills("写测试", packs=[DEFAULT_PACK])
    assert items
    for item in items:
        assert set(item) == {"name", "one_liner", "reason"}
        assert item["name"] and item["one_liner"]
        assert len(item["reason"]) <= 20  # 理由 ≤20 字代码硬约束


def test_recommend_skills_prefers_matching_skill() -> None:
    """命中关键字的排前（tdd 的 one_liner 含"测试"）。"""
    items = recommend_skills("测试", packs=[DEFAULT_PACK], limit=3)
    assert items[0]["name"] == "tdd"


def test_recommend_skills_empty_packs_yields_nothing() -> None:
    """显式空清单 → 无推荐（falsy 陷阱同法，不回退全集）。"""
    assert recommend_skills("测试", packs=[]) == []


def test_recommend_skills_none_packs_is_full_set() -> None:
    assert len(recommend_skills("测试", packs=None)) >= 1


def test_render_skill_recommendations_formats_lines() -> None:
    text = render_skill_recommendations(
        [{"name": "tdd", "one_liner": "红绿重构", "reason": "适合写测试"}]
    )
    assert "推荐技能：tdd" in text
    assert "红绿重构" in text


def test_render_skill_recommendations_empty() -> None:
    assert render_skill_recommendations([]) == "（无可推荐技能）"


# ---- 图内分派（_actor_tool_runner）----

def test_runner_dispatches_ask_user_question(tmp_path: pathlib.Path) -> None:
    runner, _knobs = _actor_tool_runner({"workspace_root": str(tmp_path)})
    result = runner("AskUserQuestion", {"question_text": "要几个文件？", "options": ["一", "多"]})
    assert result.ok
    assert "要几个文件？" in result.content
    assert "1. 一" in result.content


def test_runner_ask_user_question_bad_args_not_ok(tmp_path: pathlib.Path) -> None:
    runner, _knobs = _actor_tool_runner({"workspace_root": str(tmp_path)})
    result = runner("AskUserQuestion", {"question_text": ""})
    assert result.ok is False


def test_runner_dispatches_skill_recommend(tmp_path: pathlib.Path) -> None:
    runner, _knobs = _actor_tool_runner(
        {"workspace_root": str(tmp_path), "skill_packs": [DEFAULT_PACK]}
    )
    result = runner("SkillRecommend", {"purpose": "测试", "limit": 2})
    assert result.ok
    assert "推荐技能：" in result.content


def test_runner_skill_recommend_respects_empty_packs(tmp_path: pathlib.Path) -> None:
    runner, _knobs = _actor_tool_runner(
        {"workspace_root": str(tmp_path), "skill_packs": []}
    )
    result = runner("SkillRecommend", {"purpose": "测试"})
    assert "无可推荐技能" in result.content


# ---- 端到端：模型经工具环调用 ----

class _AskModel:
    def __init__(self) -> None:
        self._script = [
            ToolAwareResult(
                text="我需要问一下",
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="AskUserQuestion",
                        arguments={
                            "question_text": "先做哪个模块？",
                            "explanation": "决定排期",
                            "options": ["记账", "报表"],
                        },
                    ),
                ),
            ),
            ToolAwareResult(text="等你回答后继续"),
        ]

    def complete(self, messages, *, role, thread_id):  # pragma: no cover
        return ModelResult(text="unused")

    def complete_with_tools(self, messages, tools, *, role, thread_id):
        return self._script.pop(0)


def test_actor_tool_loop_can_ask_user(tmp_path: pathlib.Path) -> None:
    """模型经工具环提问：工具被真实调用且成功（结果在回灌历史，终稿由模型决定）。"""
    state = {
        "task_brief": "记账",
        "build_way": "way3",
        "workspace_root": str(tmp_path),
        "actor_messages": [],
    }
    updates = make_actor_node(_AskModel())(state, None)
    content = updates["actor_messages"][0].content
    assert "AskUserQuestion" in content
    assert "工具调用 1 次（成功 1）" in content


def test_ask_tools_declared_in_schema() -> None:
    from project_agent.tools.tool_loop import TOOL_SCHEMAS

    assert "AskUserQuestion" in TOOL_SCHEMAS
    assert "SkillRecommend" in TOOL_SCHEMAS
