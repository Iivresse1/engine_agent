"""入口路由器：START 后纯代码条件边——相位重建（spec v1.1『入口路由真值表』）。

02 票：真值表 +问卷两行（部分填写→ask_tasks；task_brief 已设+字段缺→build_ways）。
05 票：行 3 落地——todos 为空（falsy）→ planner（新计划轮）。
行序即优先级；guidance_trigger 相位由 build_ways 条件边接入（非 START 路由）。
"""

from __future__ import annotations

from typing import Any, Mapping

ASK_TASKS = "ask_tasks"
BUILD_WAYS = "build_ways"
GUIDANCE_TRIGGER = "guidance_trigger"
PLANNER = "planner"

END_MAP: dict[str, str] = {
    ASK_TASKS: ASK_TASKS,
    BUILD_WAYS: BUILD_WAYS,
    PLANNER: PLANNER,
}

ENTRY_TRUTH_TABLE: list[tuple[dict[str, Any], str]] = [
    ({}, ASK_TASKS),
    ({"task_brief": ""}, ASK_TASKS),
    ({"build_way": "way4"}, ASK_TASKS),
    ({"user_mode": "novice"}, ASK_TASKS),  # 02：问卷部分填写+简报未设
    (
        {"user_mode": "novice", "guidance_pref": "auto", "skill_packs": []},
        ASK_TASKS,  # skill_packs=[] 合法已设——问卷仍走 ask_tasks（简报未设）
    ),
    ({"task_brief": "一个想法"}, BUILD_WAYS),
    ({"task_brief": "x", "build_way": ""}, BUILD_WAYS),
    ({"task_brief": "x", "user_mode": None}, BUILD_WAYS),  # 02：01 遗留会话
    ({"task_brief": "x", "build_way": "way4"}, PLANNER),  # 05 行 3：todos 空→新计划
    (
        {
            "task_brief": "x",
            "build_way": "way4",
            "selected_proposal": 0,
            "todos": [{"content": "t", "status": "pending"}],
            "main_loop_count": 2,
            "turn_end_reason": "round",
        },
        PLANNER,  # 05：todos 已设（工作相位路由随后续切片落位）
    ),
]


def entry_route(dashboard: Mapping[str, Any]) -> str:
    if not dashboard.get("task_brief"):
        return ASK_TASKS
    if not dashboard.get("build_way"):
        return BUILD_WAYS
    return PLANNER


def route_from_start(state: Mapping[str, Any]) -> str:
    """图条件边函数：读仪表盘重建本轮相位（纯代码，零 LLM）。"""
    return entry_route(state)
