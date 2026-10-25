"""09 票 B 段：skills 技能懒加载——技能头 + 触发全文 + 推荐理由 ≤20。

接缝：skills 模块公开 API（SkillHead / SKILLS / skill_heads / skill_body /
recommendation_reason）。懒加载语义（GLOSSARY）：上下文只注名字+一句话，
SKILL.md 全文在被触发时才读入——skill_body 即"触发时全文读入"的语义桩。
"""

from __future__ import annotations

from project_agent.skills import (
    SKILLS,
    SkillHead,
    recommendation_reason,
    skill_body,
    skill_heads,
)


def test_skill_heads_list_three_skills():
    """技能头三件：grilling / tdd / to-spec（名字+一句话）。"""
    heads = skill_heads()
    assert heads == SKILLS
    assert [(h.name, h.one_liner) for h in heads] == [
        ("grilling", "连珠追问压测计划"),
        ("tdd", "红绿重构测试先行"),
        ("to-spec", "把决策沉淀为规格"),
    ]
    assert all(isinstance(h, SkillHead) for h in heads)


def test_skill_head_is_frozen_value_object():
    head = SkillHead(name="tdd", one_liner="红绿重构测试先行")
    assert head.name == "tdd"
    assert head.one_liner == "红绿重构测试先行"
    assert head == SkillHead(name="tdd", one_liner="红绿重构测试先行")


def test_skill_body_returns_full_text_on_hit():
    """命中 → 返回 SKILL.md 全文形态：# {name} 标题 + one_liner 展开的说明。"""
    body = skill_body("tdd")
    assert body is not None
    assert body.startswith("# tdd\n\n")
    assert "红绿重构测试先行" in body
    # 全文是展开的说明文本（约 200 字），不是一句话复读
    assert len(body) > 100


def test_skill_body_each_known_skill_has_body():
    for head in SKILLS:
        body = skill_body(head.name)
        assert body is not None
        assert body.startswith(f"# {head.name}\n\n")
        assert head.one_liner in body
        assert len(body) > 100


def test_skill_body_miss_returns_none():
    """未命中 → None（无此技能即无全文可载）。"""
    assert skill_body("nosuch") is None
    assert skill_body("") is None
    assert skill_body("TDD") is None  # 名字精确匹配


def test_recommendation_reason_within_limit_passes_through():
    """≤20 字照放。"""
    assert recommendation_reason("个人作品有沉淀不臃肿") == "个人作品有沉淀不臃肿"
    assert recommendation_reason("") == ""


def test_recommendation_reason_over_limit_truncated_to_20():
    """验收 5：>20 字被代码层截断（30 字理由 → 20）。"""
    reason_30 = "一二三四五六七八九十" * 3  # 精确 30 字
    assert len(reason_30) == 30
    clipped = recommendation_reason(reason_30)
    assert clipped == reason_30[:20]
    assert len(clipped) == 20
    # 恰好 21 字 → 20
    reason_21 = "一" * 21
    assert recommendation_reason(reason_21) == "一" * 20
