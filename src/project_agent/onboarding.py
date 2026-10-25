r"""首启问卷：四问规格 + 自由文本解释引擎 + guidance_mode 纯配置映射。

【Q4 选项为发明】：spec 用户故事只钉定 Q1–Q3 文案；Q4（技能包
"默认技能包/暂不启用"→["default"]/[]）为 02 票实现发明，报告已标注。

13 票文案润色（用户裁定："可读性非常差，看到会生气"）：问题主体 +
一句话解释（explanation 进 question 断点 payload，渲染层单独一行不加粗），
选项统一"标签 —— 说明"式（rendering.py 按" —— "切分主体/说明）。
keywords 原词全保留 + 新增长标签稳定子串。

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
        field="user_mode",
        question_text="你的编程基础 —— 决定 agent 用多大深度和你沟通",
        explanation="这会影响讲解的详略和术语的密度",
        options=(
            "有编程经验 —— 看得懂代码，直接谈实现",
            "编程新手 —— 需要逐步解释每一步在做什么",
        ),
        values=("experienced", "novice"),
        # novice 词在前：防"零基础"含"基础"误判为 experienced
        keywords=(
            ("不了解编程", "novice"),
            ("零基础", "novice"),
            ("新手", "novice"),
            ("小白", "novice"),
            ("逐步解释", "novice"),
            ("不懂代码", "novice"),
            ("看得懂", "experienced"),
            ("有编程经验", "experienced"),
            ("基础", "experienced"),
            ("经验", "experienced"),
            ("程序员", "experienced"),
        ),
    ),
    QuestionSpec(
        field="guidance_pref",
        question_text="新手指引 —— 构建过程中要不要配讲解",
        explanation="讲解会说明每轮为什么这么做、涉及哪些技术",
        options=(
            "自动讲解 —— 每轮自动附带一段说明",
            "每轮问我 —— 讲不讲由我当场决定",
            "关闭 —— 不需要讲解",
        ),
        values=("auto", "ask", "off"),
        keywords=(
            ("自动", "auto"),
            ("每轮自动", "auto"),
            ("询问", "ask"),
            ("问我", "ask"),
            ("当场决定", "ask"),
            ("问一问", "ask"),
            ("关", "off"),
            ("不需要", "off"),
        ),
        novice_hint="（新手推荐选 1）",
    ),
    QuestionSpec(
        field="decision_mode",
        question_text="关键决策把关 —— 重要选择谁来拍板",
        explanation="涉及技术选型、文件改动等关键动作时的确认策略",
        options=(
            "AI 自动审核 —— 常规自动通过，高风险才来问我",
            "全部人工 —— 每个决策都先经我确认",
        ),
        values=("ai_review", "manual"),
        keywords=(
            ("自动审核", "ai_review"),
            ("自动通过", "ai_review"),
            ("ai", "ai_review"),
            ("人工", "manual"),
            ("先经我确认", "manual"),
            ("我自己来", "manual"),
        ),
    ),
    QuestionSpec(
        field="skill_packs",
        question_text="技能包 —— 内置的工作方法集合，启用吗",
        explanation="技能是预置的做事套路，比如测试先行、追问压测",
        options=(
            "启用默认包 —— 通用工作方法全量加载",
            "暂不启用 —— 以后随时用 /skills 添加",
        ),
        values=(["default"], []),
        # "暂不/不启用/以后" 在 "启用/默认" 前：防"暂不启用"误判
        keywords=(
            ("暂不", []),
            ("不启用", []),
            ("不要", []),
            ("以后", []),
            ("/skills", []),
            ("默认", ["default"]),
            ("全量加载", ["default"]),
            ("技能包", ["default"]),
        ),
    ),
)

_BY_FIELD: dict[str, QuestionSpec] = {q.field: q for q in QUESTIONNAIRE}

# 序号匹配：裸 ^[\W_]*([1-9])[\W_]*$ 或语境 (?:第|选项|方式|选)\s*([1-9])
_BARE_INDEX = re.compile(r"^[\W_]*([1-9])[\W_]*$")
_CONTEXTUAL_INDEX = re.compile(r"(?:第|选项|方式|选)\s*([1-9])")


def next_unset_field(dashboard: Mapping[str, Any]) -> str | None:
    """问卷未完：找第一个未设字段。

    判"未设"必须 value is None or value == ""——skill_packs=[] 是合法已设值
    （falsy 陷阱：不得用 truthy 判断）。
    """
    for q in QUESTIONNAIRE:
        value = dashboard.get(q.field)
        if value is None or value == "":
            return q.field
    return None


def question_for(field: str) -> QuestionSpec:
    return _BY_FIELD[field]


def interpret_answer(spec: QuestionSpec, text: str | None) -> Any:
    """自由文本 → 受控值；解释不了返回 None（返回 [] 是合法值，判 None 不得用 truthy）。

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
