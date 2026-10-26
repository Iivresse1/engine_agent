"""AskUserQuestion / SkillRecommend 工具本体（17 票补，清两条欠账）。

两者都是**结构性工具**——不执行副作用，而是返回"该走哪一步"的信号：

- `AskUserQuestion`：模型调它 = 请求向用户提问。工具本身不阻塞等待（图内零
  interrupt 是 ADR-0001 的硬约束），只把问题结构化返回；**调用方（actor）
  据此把问题写进 `turn_end_payload` 走提问断点**——这就是 spec 说的
  "AskUserQuestion 实现为提问断点"。
- `SkillRecommend`：模型调它 = 请求推荐技能。按 `skill_packs` 与阶段筛选，
  返回 `名字 + 一句话 + ≤20 字理由`，理由由代码截断（硬约束在代码层）。

设计边界：本层纯函数，零 I/O、零网络、零图依赖；执行结果经 `tool_loop` 回灌。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from project_agent.skills import recommendation_reason, skill_heads


@dataclass(frozen=True)
class QuestionRequest:
    """模型请求的提问（结构化的提问断点素材）。"""

    text: str
    explanation: str
    options: tuple[str, ...] = ()
    asker: str = "actor"

    def to_payload(self) -> dict[str, Any]:
        """转成 `question` 断点的 payload 形状（与协议表逐字对齐）。"""
        payload: dict[str, Any] = {
            "question_text": self.text,
            "explanation": self.explanation,
            "options": list(self.options),
            "asker": self.asker,
        }
        return payload


def ask_user_question(
    question_text: str,
    explanation: str = "",
    options: list[str] | tuple[str, ...] | None = None,
    asker: str = "actor",
) -> QuestionRequest:
    """构造提问请求（**不阻塞**——调用方把它变成 turn_end_payload）。"""
    text = str(question_text or "").strip()
    if not text:
        raise ValueError("question_text 不能为空")
    normalized = tuple(str(option).strip() for option in (options or ()) if str(option).strip())
    return QuestionRequest(
        text=text,
        explanation=str(explanation or "").strip() or "选它的后果见下一行",
        options=normalized,
        asker=str(asker or "actor"),
    )


def recommend_skills(
    purpose: str,
    *,
    packs: list[str] | tuple[str, ...] | None = None,
    limit: int = 3,
) -> list[dict[str, str]]:
    """按用途与已选包推荐技能：`[{name, one_liner, reason}]`（理由 ≤20 字）。

    `packs=None` → 全集（向后兼容）；空清单 → 空（显式不要技能，falsy 陷阱同法）。
    """
    heads = skill_heads(None if packs is None else list(packs))
    query = str(purpose or "").strip().lower()
    scored: list[tuple[int, Any]] = []
    for head in heads:
        haystack = f"{head.name} {head.one_liner}".lower()
        score = sum(1 for token in query.split() if token and token in haystack)
        scored.append((score, head))
    # 有命中词的排前，其余保序；封顶 limit
    scored.sort(key=lambda item: -item[0])
    return [
        {
            "name": head.name,
            "one_liner": head.one_liner,
            "reason": recommendation_reason(f"适合{purpose or '当前阶段'}"),
        }
        for _score, head in scored[: max(1, int(limit))]
    ]


def render_skill_recommendations(items: list[Mapping[str, str]]) -> str:
    """把推荐结果折成一行行文本（回灌给模型 / 进 round payload）。"""
    if not items:
        return "（无可推荐技能）"
    return "\n".join(
        f"推荐技能：{item['name']}（{item['reason']}）—— {item['one_liner']}" for item in items
    )


__all__ = [
    "QuestionRequest",
    "ask_user_question",
    "recommend_skills",
    "render_skill_recommendations",
]
