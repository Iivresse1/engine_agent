"""teach-me 生成（13 票）：指引材料包 → 单发模型调用 → HTML 教学页落盘。

隔离红线（ADR-0002）与图内指引同款：role=ask_agent 单发调用，无历史
累积；返回 HTML 由**本模块代写盘**（代码层写权，不经模型工具调用——
工具执行回路仍属 v1.5 背欠），经 SharedDocs.write_any 路径防护（含
".." 拒绝，与 DemoAgent 同法）。

落盘三件（workspace_root 下 teach-me/ 目录）：
- R{n}/index.html —— 模型返回的自包含教学页全文
- learner-profile.md —— 纯代码维护的学习者画像（首启写一次）
- session.md —— 纯代码维护的教学日志（每次 teach-me 追加一行）
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from project_agent.skills import skill_body

_TEACH_ME_DIR = "teach-me"

# 指引询问四选（13 票 C 节，逐字钉死）
GUIDANCE_QUESTION_TEXT = "本轮讲解 —— 要为这轮的产出配一段讲解吗？"
GUIDANCE_EXPLANATION = "讲解会说明这轮做了什么、为什么这么做"
GUIDANCE_OPTIONS: list[str] = [
    "简短讲解 —— 一段话说明本轮要点",
    "深度教学 —— 生成一页图文教学页（HTML，含可勾选的概念清单）",
    "跳过 —— 这轮不需要讲解",
    "以后都深度教学 —— 之后每轮自动生成教学页，不再询问",
]

# 四选解释引擎：序号走裸/语境正则（与问卷同构），关键词按下表
_TEACH_CHOICE_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    # teach 必须在 brief 前："深度教学"含"教学"，单独判
    (("深度", "教学", "教我", "详细页"), "teach"),
    (("以后", "每轮都", "一直"), "teach_always"),
    (("跳过", "不要", "不用", "不用讲"), "skip"),
    (("简短", "简单", "普通", "讲一下", "说明"), "brief"),
)


def interpret_teach_choice(text: str | None) -> str | None:
    """四选解释：返回 "brief" | "teach" | "skip" | "teach_always" | None。

    "以后都深度教学" 判定优先于单轮 teach：含"以后/每轮都"字样即 teach_always
    （关键词序 teach 在前，但 always 词先单独判防吞）。
    """
    if not text or not text.strip():
        return None
    stripped = text.strip()
    # teach_always 优先：含持久词且含教学意图
    persistent = any(word in stripped for word in ("以后", "每轮都", "一直", "总是"))
    teachy = any(word in stripped for word in ("深度", "教学", "教我", "详细页"))
    if persistent and teachy:
        return "teach_always"
    if persistent and "跳过" in stripped:
        return "skip"
    if stripped in ("4",):
        return "teach_always"
    if stripped in ("1",):
        return "brief"
    if stripped in ("2",):
        return "teach"
    if stripped in ("3",):
        return "skip"
    for keywords, choice in _TEACH_CHOICE_KEYWORDS:
        if any(keyword in stripped for keyword in keywords):
            return choice
    return None


def _profile_text(state: Mapping[str, Any]) -> str:
    """学习者画像首启文本（纯代码，读仪表盘四个已设字段）。"""
    return (
        "# Learner Profile\n"
        f"Updated: {date.today().isoformat()}\n\n"
        "## Style\n"
        "- 来自首启问卷的画像（agent 自动维护）\n\n"
        "## Patterns\n"
        f"- 编程基础：{state.get('user_mode') or '未知'}\n"
        f"- 指引偏好：{state.get('guidance_pref') or '未知'}\n"
        f"- 构建方式：{state.get('build_way') or '未知'}\n"
        f"- 任务简报：{str(state.get('task_brief') or '')[:80]}\n"
    )


def ensure_profile(shared_docs: Any, state: Mapping[str, Any]) -> None:
    """画像不存在则首启写入（幂等：存在即返回）。"""
    marker = f"{_TEACH_ME_DIR}/learner-profile.md"
    root = getattr(shared_docs, "root", None)
    if root is None:
        return
    from pathlib import Path

    if (Path(root) / marker).exists():
        return
    shared_docs.write_any(marker, _profile_text(state))


def read_profile(shared_docs: Any) -> str:
    """读画像（存在才读——教学个性化输入之一；不存在返回 ""）。"""
    root = getattr(shared_docs, "root", None)
    if root is None:
        return ""
    from pathlib import Path

    path = Path(root) / _TEACH_ME_DIR / "learner-profile.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_session(shared_docs: Any) -> str:
    """读教学日志（存在才读——"已掌握的概念不要重教"的输入；"" 即首课）。"""
    root = getattr(shared_docs, "root", None)
    if root is None:
        return ""
    from pathlib import Path

    path = Path(root) / _TEACH_ME_DIR / "session.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def append_session(shared_docs: Any, round_no: int, concept_count: int) -> None:
    """教学日志追加一行（纯代码维护；不存在则带表头新建）。"""
    root = getattr(shared_docs, "root", None)
    if root is None:
        return
    from pathlib import Path

    path = Path(root) / _TEACH_ME_DIR / "session.md"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        line = f"- R{round_no}（{date.today().isoformat()}）：概念清单 {concept_count} 项\n"
        shared_docs.write_any(
            f"{_TEACH_ME_DIR}/session.md", existing + line
        )
    else:
        header = (
            "# teach-me Session Log\n\n"
            f"- R{round_no}（{date.today().isoformat()}）：概念清单 {concept_count} 项\n"
        )
        shared_docs.write_any(f"{_TEACH_ME_DIR}/session.md", header)


def build_teach_prompt(
    *,
    round_summary: str,
    doc_slice: str,
    skill_text: str,
    profile: str,
    session: str,
) -> str:
    """teach-me 单发 prompt（材料包 + 技能全文 + 画像 + 既往 session）。"""
    parts = [
        "请按以下技能要求，为本轮产出制作一页深度教学（完整 HTML 文档）：\n",
        f"【技能全文】\n{skill_text}\n",
        f"【本轮摘要】\n{round_summary}\n",
        f"【本轮文档切片】\n{doc_slice or '（无）'}\n",
    ]
    if profile:
        parts.append(f"【学习者画像】\n{profile}\n")
    if session:
        parts.append(
            f"【既往教学日志】（已掌握的概念不要重教）\n{session}\n"
        )
    parts.append(
        "\n【输出要求】只输出 HTML 全文（自包含单文件：内联 CSS、零外链、"
        "零 JS 依赖；概念清单每项带 checkbox，勾选状态存 localStorage，"
        "key=teach-me-R{n}；中文排版）。不要任何解释性前后缀。"
    )
    return "".join(parts)


def teach_page_path(round_no: int) -> str:
    """教学页相对路径（round_output 渲染用）。"""
    return f"{_TEACH_ME_DIR}/R{round_no}/index.html"


def _concept_count(html: str) -> int:
    """粗计概念清单条目数（checkbox 出现次数；0 也合法）。"""
    return html.count("checkbox")


def run_teach_me(
    model: Any,
    shared_docs: Any,
    state: Mapping[str, Any],
    *,
    round_no: int,
    round_summary: str,
    doc_slice: str,
    thread_id: str,
) -> str:
    """一次 teach-me 全流程：画像首启 → 单发调用 → 三件落盘 → 回执行。

    返回 round_output 用回执："教学页已生成：teach-me/R{n}/index.html"。
    模型未返回有效 HTML（空文本）→ 回执失败行（不落盘不记日志）。
    """
    if model is None or shared_docs is None:
        return "（teach-me 未接线：需 model 与 workspace_root）"

    ensure_profile(shared_docs, state)
    skill_text = skill_body("teach-me") or ""
    prompt = build_teach_prompt(
        round_summary=round_summary,
        doc_slice=doc_slice,
        skill_text=skill_text,
        profile=read_profile(shared_docs),
        session=read_session(shared_docs),
    )
    result = model.complete(
        [{"role": "user", "content": prompt}],
        role="ask_agent",
        thread_id=thread_id,
    )
    html = str(result.text).strip()
    if not html:
        return f"（teach-me 生成失败：模型返回空文本，R{round_no} 未落盘）"

    page_rel = teach_page_path(round_no)
    ok = shared_docs.write_any(page_rel, html)
    if not ok:
        return f"（teach-me 落盘被拒：路径 {page_rel} 含非法段）"
    append_session(shared_docs, round_no, _concept_count(html))
    return f"教学页已生成：{page_rel}"


__all__ = [
    "GUIDANCE_EXPLANATION",
    "GUIDANCE_OPTIONS",
    "GUIDANCE_QUESTION_TEXT",
    "append_session",
    "build_teach_prompt",
    "ensure_profile",
    "interpret_teach_choice",
    "read_profile",
    "read_session",
    "run_teach_me",
    "teach_page_path",
]
