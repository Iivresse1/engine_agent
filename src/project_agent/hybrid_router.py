"""REPL 混合路由三层（11 票终裁 C，验收 3/4）。

所有用户输入先过分层路由，层序即优先级：

1. 显式斜杠（text.startswith("/")）→ "slash"：零 LLM，命令分发。
2. 报错特征规则预筛（Traceback / Error: / 常见异常类正则）**且** 当前
   demo 阶段活跃（last_state["demo_phase"]=="building"）→ "error_return"：
   贴 Traceback 无命令直接进 DemoAgent 修复环（零 LLM）。
3. LLM 窄分类兜底（仅当注入 error_classifier）→ 只判"报错回传 vs 普通输入"
   二分：响应含"报错"→ "error_return"，否则 "normal"；未注入 → "normal"
   （默认去活跃 agent/Builder，即 REPL 既有融合路径）。

纯函数：不读文件、不写 state；分类器按 ModelClient 形态调用（role="router"）。
"""

from __future__ import annotations

import re
from typing import Any, Mapping

# 报错特征（规则预筛，re.MULTILINE）：Traceback 头 / 行首 Error[:：] /
# 三类高频异常类名——命中即"贴的是报错"，无需模型判定。
ERROR_PATTERN = re.compile(
    r"(Traceback \(most recent call last\)|^\s*Error[:：]|SyntaxError|"
    r"ModuleNotFoundError|ZeroDivisionError)",
    re.MULTILINE,
)

ROUTER_ROLE = "router"
_ERROR_KEYWORD = "报错"


def route_input(
    text: str,
    *,
    last_state: Mapping[str, Any] | None = None,
    error_classifier: Any = None,
) -> str:
    """三层序路由：返回 "slash" | "error_return" | "normal"（纯函数）。"""
    if text.startswith("/"):
        return "slash"

    state = last_state or {}
    if state.get("demo_phase") == "building" and ERROR_PATTERN.search(text):
        return "error_return"

    if error_classifier is not None:
        result = error_classifier.complete(
            [{"role": "user", "content": text}],
            role=ROUTER_ROLE,
            thread_id=str(state.get("thread_id") or ""),
        )
        if _ERROR_KEYWORD in str(result.text):
            return "error_return"
    return "normal"


__all__ = ["ERROR_PATTERN", "ROUTER_ROLE", "route_input"]
