"""首启问卷：QuestionSpec/QUESTIONNAIRE/解释引擎/guidance_mode_mapping（表驱动）。"""

from __future__ import annotations

import dataclasses

import pytest

from project_agent.onboarding import (
    QUESTIONNAIRE,
    QuestionSpec,
    guidance_mode_mapping,
    interpret_answer,
    next_unset_field,
    question_for,
)


def test_questionnaire_has_four_specs_in_order():
    assert [q.field for q in QUESTIONNAIRE] == [
        "user_mode",
        "guidance_pref",
        "decision_mode",
        "skill_packs",
    ]


def test_option_texts_align_glossary_and_user_stories():
    """选项文案精确对齐：Q1 编程基础；Q2 三态；Q3 决策；Q4 技能包。"""
    by_field = {q.field: q for q in QUESTIONNAIRE}
    assert list(by_field["user_mode"].options) == ["有一定编程基础", "我不了解编程"]
    assert list(by_field["user_mode"].values) == ["experienced", "novice"]
    assert list(by_field["guidance_pref"].options) == ["自动每轮", "每轮询问", "关"]
    assert list(by_field["guidance_pref"].values) == ["auto", "ask", "off"]
    assert list(by_field["decision_mode"].options) == ["AI 自动审核", "全权人工"]
    assert list(by_field["decision_mode"].values) == ["ai_review", "manual"]
    assert list(by_field["skill_packs"].options) == ["默认技能包", "暂不启用"]
    assert list(by_field["skill_packs"].values) == [["default"], []]


def test_next_unset_field_treats_empty_list_as_set():
    """skill_packs=[] 是合法已设值（falsy 陷阱）。"""
    assert next_unset_field({}) == "user_mode"
    assert next_unset_field({"user_mode": "novice"}) == "guidance_pref"
    assert next_unset_field({"skill_packs": None}) == "user_mode"
    assert next_unset_field({"skill_packs": []}) == "user_mode"
    assert (
        next_unset_field(
            {"user_mode": "experienced", "guidance_pref": "", "skill_packs": []}
        )
        == "guidance_pref"
    )
    assert (
        next_unset_field(
            {
                "user_mode": "novice",
                "guidance_pref": "auto",
                "decision_mode": "manual",
                "skill_packs": [],
            }
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "text", "expected"),
    [
        # 序号优先
        ("user_mode", "1", "experienced"),
        ("user_mode", " 2 ", "novice"),
        ("guidance_pref", "3", "off"),
        ("user_mode", "选 1", "experienced"),
        ("user_mode", "选项2", "novice"),
        ("user_mode", "第1种", "experienced"),
        ("user_mode", "方式 2", "novice"),
        # 关键词（Q1 novice 词在前防"零基础"含"基础"误判）
        ("user_mode", "我不了解编程", "novice"),
        ("user_mode", "零基础", "novice"),
        ("user_mode", "新手小白", "novice"),
        ("user_mode", "有一定编程基础", "experienced"),
        ("user_mode", "有编程经验", "experienced"),
        ("user_mode", "程序员", "experienced"),
        ("guidance_pref", "自动每轮", "auto"),
        ("guidance_pref", "自动", "auto"),
        ("guidance_pref", "每轮询问", "ask"),
        ("guidance_pref", "问我", "ask"),
        ("guidance_pref", "关", "off"),
        ("decision_mode", "AI 自动审核", "ai_review"),
        ("decision_mode", "自动审核", "ai_review"),
        ("decision_mode", "全权人工", "manual"),
        ("decision_mode", "人工", "manual"),
        ("decision_mode", "我自己来", "manual"),
        # Q4 "暂不/不启用" 在 "启用" 前
        ("skill_packs", "默认技能包", ["default"]),
        ("skill_packs", "默认", ["default"]),
        ("skill_packs", "暂不启用", []),
        ("skill_packs", "不启用", []),
        ("skill_packs", "不要", []),
        # 解释不了
        ("user_mode", "做个 2048 游戏", None),
        ("user_mode", "随便说", None),
        ("guidance_pref", "嗯", None),
        ("skill_packs", "呃", None),
    ],
)
def test_interpret_answer(field, text, expected):
    spec = question_for(field)
    assert spec.field == field
    assert interpret_answer(spec, text) == expected


def test_interpret_answer_none_for_blank():
    assert interpret_answer(question_for("user_mode"), "") is None
    assert interpret_answer(question_for("user_mode"), None) is None


def test_interpret_answer_returns_empty_list_legally():
    """interpret_answer 返回 [] 是合法已设值——判 None 不得用 truthy。"""
    result = interpret_answer(question_for("skill_packs"), "暂不启用")
    assert result is not None
    assert result == []


def test_novice_hint_appended_for_novice():
    """user_mode==novice 时 Q2 追加"；新手推荐 1"。"""
    base = question_for("guidance_pref")
    hinted = dataclasses.replace(base, novice_hint="；新手推荐 1")
    assert hinted.novice_hint == "；新手推荐 1"


# ---------- guidance_mode_mapping（纯函数表驱动） ----------


@pytest.mark.parametrize(
    ("build_way", "guidance_pref", "user_mode", "expected"),
    [
        ("way1", "auto", "experienced", "off"),  # way1 纯对话无构建轮可指引
        ("way1", "ask", "novice", "off"),
        ("way1", "off", "novice", "off"),
        ("way2", "auto", "experienced", "auto"),  # guidance_pref 优先
        ("way3", "ask", "novice", "ask"),
        ("way4", "off", "experienced", "off"),
        ("way2", "off", "novice", "off"),
        ("way2", None, "novice", "auto"),  # novice+未设→auto（故事 6）
        ("way3", None, "experienced", "off"),  # 其余→off
        ("way2", "", "novice", "auto"),  # 空串=未设
        (None, "auto", "experienced", "off"),  # build_way 未设→off
        ("", "ask", "novice", "off"),
        ("way4", "auto", None, "auto"),  # user_mode 未设不阻断 pref
    ],
)
def test_guidance_mode_mapping(build_way, guidance_pref, user_mode, expected):
    assert guidance_mode_mapping(build_way, guidance_pref, user_mode) == expected


def test_question_spec_is_frozen():
    spec = QuestionSpec(
        field="x",
        question_text="q",
        options=["a"],
        values=["v"],
        keywords=["a"],
        novice_hint=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.field = "y"
