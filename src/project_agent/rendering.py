"""断点渲染（13 票）：问题主体加粗 + 解释缩进 + 选项编号（DSH 式三层可读性）。

加粗只在交互 TTY 生效：管道/重定向态退化为纯文本——输出被日志收集时
不带 ANSI 转义污染（冒烟脚本/CI 断言均可直接比字符串）。

渲染是纯函数（payload → 行列表），单独可测，不碰 I/O。
"""

from __future__ import annotations

import sys
from typing import Any, Mapping

_BOLD = "\x1b[1m"
_RESET = "\x1b[0m"


def supports_ansi(stream: Any = None) -> bool:
    """TTY 才上色（Windows Terminal / Unix 终端皆为 True；管道 False）。"""
    target = stream if stream is not None else sys.stdout
    isatty = getattr(target, "isatty", None)
    try:
        return bool(isatty()) if callable(isatty) else False
    except (ValueError, OSError):
        return False


def _bold(text: str, ansi: bool) -> str:
    return f"{_BOLD}{text}{_RESET}" if ansi else text


def split_option(option: str) -> tuple[str, str]:
    """选项串 → (主体, 说明)：按全角破折号" —— "切分；无分隔则说明为 ""。

    文案约定（13 票 C 节）：选项形如"标签 —— 一句话说明"。
    """
    head, sep, tail = option.partition(" —— ")
    if not sep:
        return option.strip(), ""
    return head.strip(), tail.strip()


def render_question_payload(
    payload: Mapping[str, Any], *, ansi: bool | None = None
) -> list[str]:
    """question 断点 → 终端行列表。

    第一行：加粗的问题主体（question_text 去掉解释部分后的主体）
    第二行：解释（不加粗，缩进两级）
    其后：选项逐行编号，主体加粗、说明不加粗
    末尾：asker 行（谁在问）
    """
    use_ansi = supports_ansi() if ansi is None else ansi
    text = str(payload.get("question_text") or "")
    explanation = str(payload.get("explanation") or "")
    subject, _, inline_expl = text.partition(" —— ")
    # 兼容：解释仍在 question_text 内嵌（旧发射点未拆）时取内嵌段
    if inline_expl.strip() and not explanation:
        explanation = inline_expl.strip()
    lines = [f"  {_bold(subject.strip(), use_ansi)}"]
    if explanation:
        lines.append(f"    {explanation}")
    options = [str(option) for option in (payload.get("options") or [])]
    for index, option in enumerate(options, start=1):
        head, tail = split_option(option)
        suffix = f" —— {tail}" if tail else ""
        lines.append(f"    {index}. {_bold(head, use_ansi)}{suffix}")
    asker = payload.get("asker")
    if asker:
        lines.append(f"    （提问者：{asker}）")
    return lines


__all__ = ["render_question_payload", "split_option", "supports_ansi"]
