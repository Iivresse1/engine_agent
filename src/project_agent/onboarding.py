r"""首启问卷（14 票重编排后仅存指引一题）+ 解释引擎 + guidance_mode 纯配置映射。

问卷演进史：02 票四问（基础/指引/把关/技能包）→ 14 票 Q65 裁定重编排——
①"今天要做什么呢？"为 REPL 开场提示语（首条自由文本即图输入）②build_ways
③指引一问挪至 build_ways 决议后（guidance_trigger 节点发射与消费）。
user_mode 由指引答案推导（auto/ask→novice、off→experienced）；decision_mode
移入应用级配置窗口；skill_packs 默认 ["default"] 由 REPL 种子注入。

解释引擎序号正则 \W 不含汉字——"做个 2048 游戏"这类自由文本不会误中。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class QuestionSpec:
    field: str
    question_text: str
    options: tuple[str, ...]
    values: tuple[Any, ...]
    keywords: tuple[tuple[str, Any], ...]
    novice_hint: str | None = None
    explanation: str = ""


QUESTIONNAIRE: tuple[QuestionSpec, ...] = (
    QuestionSpec(
        field="guidance_pref",
        question_text="需要每轮给出指引帮助更好的理解项目吗 —— 构建时配讲解",
        explanation="讲解会说明每轮为什么这么做、涉及哪些技术，边构建边学",
        options=(
            "需要 —— 每轮自动附一段讲解",
            "先问我 —— 讲不讲当场决定",
            "不需要 —— 我自己看得懂",
        ),
        values=("auto", "ask", "off"),
        keywords=(
            # 否定词在前：防"不需要"含"需要"误判为 auto（与 skill_packs 同法）
            ("不需要", "off"),
            ("不用", "off"),
            ("看得懂", "off"),
            ("关", "off"),
            ("需要", "auto"),
            ("自动", "auto"),
            ("先问", "ask"),
            ("问我", "ask"),
            ("询问", "ask"),
            ("当场决定", "ask"),
        ),
    ),
)

_BY_FIELD: dict[str, QuestionSpec] = {q.field: q for q in QUESTIONNAIRE}

# 序号匹配：裸 ^[\W_]*([1-9])[\W_]*$ 或语境 (?:第|选项|方式|选)\s*([1-9])
_BARE_INDEX = re.compile(r"^[\W_]*([1-9])[\W_]*$")
_CONTEXTUAL_INDEX = re.compile(r"(?:第|选项|方式|选)\s*([1-9])")


def next_unset_field(dashboard: Mapping[str, Any]) -> str | None:
    """问卷未完：找第一个未设字段（判 None 或 ""，不用 truthy）。"""
    for q in QUESTIONNAIRE:
        value = dashboard.get(q.field)
        if value is None or value == "":
            return q.field
    return None


def question_for(field: str) -> QuestionSpec:
    return _BY_FIELD[field]


def interpret_answer(spec: QuestionSpec, text: str | None) -> Any:
    """自由文本 → 受控值；解释不了返回 None。

    序号优先（裸/语境）→ 关键词按序。
    """
    if not text or not text.strip():
        return None
    text = text.strip()

    m = _BARE_INDEX.match(text) or _CONTEXTUAL_INDEX.search(text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(spec.values):
            return spec.values[n - 1]
        return None

    lowered = text.lower()
    for keyword, value in spec.keywords:
        if keyword in text or keyword in lowered:
            return value
    return None


def guidance_mode_mapping(
    build_way: str | None, guidance_pref: str | None, user_mode: str | None
) -> str:
    """三态纯配置映射（spec 节点表：guidance_trigger 只写 guidance_mode）。

    - build_way=="way1" → off：纯对话无构建轮可指引（节点表读 build_way 的理由）
    - guidance_pref 已设 → 优先
    - novice + pref 未设 → auto（用户故事 6）
    - 其余 → off
    """
    if not build_way:
        return "off"
    if build_way == "way1":
        return "off"
    if guidance_pref:
        return guidance_pref
    if user_mode == "novice":
        return "auto"
    return "off"


__all__ = [
    "QUESTIONNAIRE",
    "QuestionSpec",
    "guidance_mode_mapping",
    "interpret_answer",
    "next_unset_field",
    "question_for",
]
