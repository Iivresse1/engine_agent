"""指引链接验证（用户故事 36）：抽取文档链接并标注死链。

形态：指引/教学文本里的 http(s) 链接先**抽取**，再经 `verify_link` 判定可达性；
不可达的链接在文本里就地标注 `（链接未验证）`，**不删链接**——用户仍可自行
打开，但不会被死链白白浪费（用户故事 36 的原话）。

设计边界：本层默认**不联网**（`fetch=None` → 不改文本），联网由调用方注入
`fetch`（Q39 红线同法：网络能力只能由用户主动动作引入）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Callable

# 只吃 ASCII URL 字符——中文标点/汉字一律终止匹配（否则"a。与"会被整段吞进 URL）
_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
_TRAILING = ".,;:!?、。，；：！？"


def extract_links(text: str) -> tuple[str, ...]:
    """抽取文本中的 http(s) 链接（去掉尾随标点，保持出现顺序，去重）。"""
    seen: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(_TRAILING)
        if url and url not in seen:
            seen.append(url)
    return tuple(seen)


def annotate_links(
    text: str,
    *,
    fetch: Callable[[str], str | None] | None = None,
    verified: Iterable[str] | None = None,
) -> str:
    """给不可达链接就地加标注。

    `fetch=None` 且 `verified` 为空 → **不改文本**（无验证能力时不乱标）。
    `verified` 是已知可达集合（复用已有验证结果，避免重复抓取）。
    """
    known = set(verified or ())
    if fetch is None and not known:
        return text

    def _dead(url: str) -> bool:
        if url in known:
            return False
        if fetch is None:
            return False
        try:
            content = fetch(url)
        except Exception:  # noqa: BLE001 - 抓取失败一律当死链
            return True
        return content is None or content == ""

    out = text
    for url in extract_links(text):
        if _dead(url):
            out = out.replace(url, f"{url}（链接未验证）", 1)
    return out


__all__ = ["annotate_links", "extract_links"]
