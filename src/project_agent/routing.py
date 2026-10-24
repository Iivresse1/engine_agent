"""入口路由器：START 后纯代码条件边——相位重建（spec v1.1『入口路由真值表』）。

01 票实现真值表前 3 行（task_brief / build_way / default 占位）；
其余行随 02+ 票逐张落位。行序即优先级。
"""

from __future__ import annotations

from typing import Any, Mapping

ASK_TASKS = "ask_tasks"
BUILD_WAYS = "build_ways"
PLACEHOLDER = "placeholder"

ENTRY_TRUTH_TABLE: list[tuple[dict[str, Any], str]] = [
    ({}, ASK_TASKS),
    ({"task_brief": ""}, ASK_TASKS),
    ({"build_way": "way4"}, ASK_TASKS),
    ({"task_brief": "一个想法"}, BUILD_WAYS),
    ({"task_brief": "x", "build_way": ""}, BUILD_WAYS),
    ({"task_brief": "x", "build_way": "way4"}, PLACEHOLDER),
    (
        {
            "task_brief": "x",
            "build_way": "way4",
            "selected_proposal": 0,
            "todos": [{"content": "t", "status": "pending"}],
            "main_loop_count": 2,
            "turn_end_reason": "round",
        },
        PLACEHOLDER,
    ),
]


def entry_route(dashboard: Mapping[str, Any]) -> str:
    if not dashboard.get("task_brief"):
        return ASK_TASKS
    if not dashboard.get("build_way"):
        return BUILD_WAYS
    return PLACEHOLDER


def route_from_start(state: Mapping[str, Any]) -> str:
    """图条件边函数：读仪表盘重建本轮相位（纯代码，零 LLM）。"""
    return entry_route(state)
