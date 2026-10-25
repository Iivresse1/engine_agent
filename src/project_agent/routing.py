"""入口路由器：START 后纯代码条件边——相位重建（spec v1.1『入口路由真值表』）。

02 票：真值表 +问卷两行（部分填写→ask_tasks；task_brief 已设+字段缺→build_ways）。
05 票：行 3——todos 空→planner；行 4——todos 未清→context_assembler（主环）；
行 5——todos 清且 task_complete 假→planner（耗尽恢复：planner 见 count>=5 清零）；
行 6——任一环计数>=5→loop_exhausted；行 7——task_complete 真→docs_done（11 改道）。
07 票：新行插在行 3 前——way4 且 selected_proposal 未设且 todos 未设 →
PROPOSALS（三方案并行先于计划）。
11 票：行 7 由 END 改道 DOCS_DONE（demo 决议断点）；行 7 前插 demo 行——
task_complete 真且 demo_phase=="building" → DEMO_AGENT（报错回传环入口；
demo 环计数>=5 由行 6 先行压过）。
行序即优先级；guidance_trigger 相位由 build_ways 条件边接入（非 START 路由）。
"""

from __future__ import annotations

from typing import Any, Mapping

from langgraph.graph import END

ASK_TASKS = "ask_tasks"
BUILD_WAYS = "build_ways"
GUIDANCE_TRIGGER = "guidance_trigger"
PROPOSALS = "proposals"
PLANNER = "planner"
CONTEXT_ASSEMBLER = "context_assembler"
ACTOR = "actor"
VERIFIER = "verifier"
DOCS_DONE = "docs_done"
DEMO_AGENT = "demo_agent"
LOOP_EXHAUSTED = "loop_exhausted"

END_MAP: dict[str, str] = {
    ASK_TASKS: ASK_TASKS,
    BUILD_WAYS: BUILD_WAYS,
    PROPOSALS: PROPOSALS,
    PLANNER: PLANNER,
    CONTEXT_ASSEMBLER: CONTEXT_ASSEMBLER,
    DOCS_DONE: DOCS_DONE,
    DEMO_AGENT: DEMO_AGENT,
    LOOP_EXHAUSTED: LOOP_EXHAUSTED,
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
    # 07 新行（行 3 前）：way4 且 selected_proposal 未设且 todos 未设 →
    # PROPOSALS（三方案并行先于计划）
    ({"task_brief": "x", "build_way": "way4"}, PROPOSALS),
    # 05 行 3：todos 空（falsy）→ planner（新计划）
    ({"task_brief": "x", "build_way": "way4", "selected_proposal": 0}, PLANNER),
    # 05 行 4：todos 未清 → context_assembler（主环工作轮）
    (
        {
            "task_brief": "x",
            "build_way": "way4",
            "selected_proposal": 0,
            "todos": [{"content": "t", "status": "pending"}],
            "main_loop_count": 2,
            "turn_end_reason": "round",
        },
        CONTEXT_ASSEMBLER,
    ),
    # 05 行 4 边角：todos pending + main_loop_count=5（行 6 只在 task_complete 真时优先）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "t", "status": "pending"}],
            "main_loop_count": 5,
        },
        CONTEXT_ASSEMBLER,
    ),
    # 05 行 5：todos 清且 task_complete 假 → planner（重新规划）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": False,
        },
        PLANNER,
    ),
    # 05 行 5 边角：清+false+main_loop_count=5 → planner（耗尽恢复路径：planner 清零开新循环）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": False,
            "main_loop_count": 5,
        },
        PLANNER,
    ),
    # 05 行 6：task_complete 真 + 任一环计数>=5 → loop_exhausted（main/demo/final_check 任一）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": True,
            "main_loop_count": 5,
        },
        LOOP_EXHAUSTED,
    ),
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": True,
            "demo_loop_count": 5,
        },
        LOOP_EXHAUSTED,
    ),
    # 05 行 7：task_complete 真 → docs_done（11 改道：demo 决议断点；终检票接管前哨）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": True,
        },
        DOCS_DONE,
    ),
    # 11 demo 行（行 7 前）：demo 构建中 + task_complete 真 → DEMO_AGENT（报错回传环入口）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": True,
            "demo_phase": "building",
        },
        DEMO_AGENT,
    ),
    # 11 行 6 压过 demo 行：demo 环计数>=5 → LOOP_EXHAUSTED（报错环封顶）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": True,
            "demo_phase": "building",
            "demo_loop_count": 5,
        },
        LOOP_EXHAUSTED,
    ),
    # 11 skipped：已跳过 demo → DOCS_DONE 幂等收轮（直通终检，12 票接管）
    (
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [{"content": "a", "status": "completed"}],
            "task_complete": True,
            "demo_phase": "skipped",
        },
        DOCS_DONE,
    ),
]


def _todos_all_completed(todos: Any) -> bool:
    """纯代码三态扫描：空表→False（防御）；全 completed→True。"""
    items = list(todos or [])
    if not items:
        return False
    return all(
        isinstance(item, dict) and item.get("status") == "completed" for item in items
    )


def entry_route(dashboard: Mapping[str, Any]) -> str:
    if not dashboard.get("task_brief"):
        return ASK_TASKS
    if not dashboard.get("build_way"):
        return BUILD_WAYS
    # 07 新行（行 3 前）：way4 方案先于计划——selected_proposal 未设且
    # todos 未设 → PROPOSALS（三方案并行节点）
    if (
        dashboard.get("build_way") == "way4"
        and dashboard.get("selected_proposal") is None
        and not (dashboard.get("todos") or [])
    ):
        return PROPOSALS
    todos = dashboard.get("todos") or []
    if not todos:  # 行 3：todos 空（falsy）→ planner（新计划）
        return PLANNER
    if not _todos_all_completed(todos):
        return CONTEXT_ASSEMBLER  # 行 4：todos 未清→主环入口（count5 边角仍此行）
    if not dashboard.get("task_complete"):
        return PLANNER  # 行 5：todos 清且 task_complete 假→重新规划（count5 边角仍此行——planner 清零恢复）
    if any(
        (dashboard.get(key) or 0) >= 5
        for key in ("main_loop_count", "demo_loop_count", "final_check_loop_count")
    ):
        return LOOP_EXHAUSTED  # 行 6：任一环计数>=5（demo 报错环封顶在此先行）
    if dashboard.get("demo_phase") == "building":
        return DEMO_AGENT  # 11 行 7 前：demo 构建中（报错回传环入口）
    return DOCS_DONE  # 行 7（11 改道）：task_complete 真→demo 决议断点


def _after_docs_done(state: Mapping[str, Any]) -> str:
    """docs_done 出口条件边（11 票终裁 A，纯函数）：三态路由。

    demo_phase=="building" → DEMO_AGENT（同轮接 demo，turn_end 由后节点写）；
    "skipped" / 未决（断点收轮）→ END。
    """
    if state.get("demo_phase") == "building":
        return DEMO_AGENT
    return END


def _after_demo(state: Mapping[str, Any]) -> str:
    """DEMO_AGENT 出口条件边（11 票终裁 B，纯函数）。

    计数封顶优先：demo_loop_count>=5 → LOOP_EXHAUSTED（报错环耗尽）；
    否则 END（每轮一个修复回合，断点收轮）。"""
    if int(state.get("demo_loop_count") or 0) >= 5:
        return LOOP_EXHAUSTED
    return END


def _after_verifier(state: Mapping[str, Any]) -> str:
    """verifier 出口条件边（05 票终裁 2，纯函数）。

    优先序：计数最前；未清→END（round 断点收轮）；清而未过→PLANNER
    （同轮重新规划）；双过→END。
    """
    if (state.get("main_loop_count") or 0) >= 5:
        return LOOP_EXHAUSTED
    todos_all_completed = _todos_all_completed(state.get("todos"))
    if todos_all_completed and state.get("task_complete"):
        return END
    if not todos_all_completed:
        return END
    return PLANNER


def route_from_start(state: Mapping[str, Any]) -> str:
    """图条件边函数：读仪表盘重建本轮相位（纯代码，零 LLM）。"""
    return entry_route(state)


def derive_actor_config(build_way: Any, guidance_mode: Any) -> dict[str, Any]:
    """8 配置派生（05 票终裁 7，验收 5）：每轮派生，不持久化不写 state。

    way∈{way1..way4} 否则默认 way1；guidance_enabled=mode∈{auto,ask}。
    05 中派生结果仅用于 actor 身体选择（way2-4 身体 07 票）。
    """
    way = build_way if build_way in ("way1", "way2", "way3", "way4") else "way1"
    return {"build_way": way, "guidance_enabled": guidance_mode in ("auto", "ask")}
