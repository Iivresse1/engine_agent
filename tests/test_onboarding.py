"""首启问卷（14 票重编排后仅存指引一题）：QuestionSpec/解释引擎/映射（表驱动）。"""

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


def test_questionnaire_has_single_guidance_spec():
    assert [q.field for q in QUESTIONNAIRE] == ["guidance_pref"]


def test_option_texts_align_glossary_and_user_stories():
    """选项文案对齐（14 票重编排："标签 —— 说明"式；指引一问三态）。"""
    by_field = {q.field: q for q in QUESTIONNAIRE}
    assert list(by_field["guidance_pref"].options) == [
        "需要 —— 每轮自动附一段讲解",
        "先问我 —— 讲不讲当场决定",
        "不需要 —— 我自己看得懂",
    ]
    assert list(by_field["guidance_pref"].values) == ["auto", "ask", "off"]


def test_guidance_question_text_and_explanation():
    spec = question_for("guidance_pref")
    assert spec.question_text == "需要每轮给出指引帮助更好的理解项目吗 —— 构建时配讲解"
    assert spec.explanation == "讲解会说明每轮为什么这么做、涉及哪些技术，边构建边学"


def test_next_unset_field_treats_blank_as_unset():
    assert next_unset_field({}) == "guidance_pref"
    assert next_unset_field({"guidance_pref": None}) == "guidance_pref"
    assert next_unset_field({"guidance_pref": ""}) == "guidance_pref"
    assert next_unset_field({"guidance_pref": "auto"}) is None
    assert next_unset_field({"guidance_pref": "off"}) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 序号优先
        ("1", "auto"),
        (" 2 ", "ask"),
        ("3", "off"),
        ("选 1", "auto"),
        ("选项2", "ask"),
        ("第3种", "off"),
        ("方式 2", "ask"),
        # 关键词
        ("需要", "auto"),
        ("需要每轮讲解", "auto"),
        ("自动", "auto"),
        ("先问", "ask"),
        ("问我", "ask"),
        ("询问", "ask"),
        ("当场决定", "ask"),
        ("不用", "off"),
        ("看得懂", "off"),
        ("关", "off"),
        # 否定词在前（前缀防误吞）："不需要"→off（与 skill_packs 同法）
        ("不需要", "off"),
        # 14 票长选项原文应可解释
        ("每轮自动附一段讲解", "auto"),
        ("讲不讲当场决定", "ask"),
        ("我自己看得懂", "off"),
        # 解释不了
        ("做个 2048 游戏", None),
        ("随便说", None),
        ("嗯", None),
    ],
)
def test_interpret_answer(text, expected):
    spec = question_for("guidance_pref")
    assert spec.field == "guidance_pref"
    assert interpret_answer(spec, text) == expected


def test_interpret_answer_none_for_blank():
    assert interpret_answer(question_for("guidance_pref"), "") is None
    assert interpret_answer(question_for("guidance_pref"), None) is None


def test_novice_hint_appended_for_novice():
    """novice_hint 字段仍可替换（dataclasses.replace 通道）。"""
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
