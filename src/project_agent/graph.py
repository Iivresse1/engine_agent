"""主工作流图：START → 入口路由（纯代码相位重建）→ 骨架节点 → END。

一轮 = 一次完整图执行；END 即断点（checkpointer 落盘、控制权交还 REPL 宿主）。
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from project_agent.nodes import (
    ask_tasks_node,
    guidance_trigger_node,
    loop_exhausted_node,
    make_assembler_node,
    make_actor_node,
    make_build_ways_node,
    make_verifier_node,
    planner_node,
)
from project_agent.routing import (
    ACTOR,
    ASK_TASKS,
    BUILD_WAYS,
    CONTEXT_ASSEMBLER,
    END_MAP,
    GUIDANCE_TRIGGER,
    LOOP_EXHAUSTED,
    PLANNER,
    VERIFIER,
    route_from_start,
    _after_verifier,
)
from project_agent.state import GraphState
from project_agent.shared_docs import SharedDocs


def new_thread_id() -> str:
    return uuid.uuid4().hex


def _after_build_ways(state: Mapping[str, Any]) -> str:
    """build_ways 出口：build_way 已设→guidance_trigger；未设（choice 断点）→END。"""
    return GUIDANCE_TRIGGER if state.get("build_way") else END


def build_graph(
    checkpointer: Any = None,
    model: Any = None,
    workspace_root: Path | None = None,
) -> Any:
    """workspace_root 非 None → SharedDocs(workspace_root) 同源注入
    assembler 与 actor 两工厂（09：assembler 读 notepad 切片/版本门，
    actor 每轮生成物带【R#】落盘 + Notepad 指令；06：同签名单注入 actor）；
    None → 不注入（05 行为，cli.py 零改动：骨架无模型本就不落盘；
    真模型票接线时传 cwd）。"""
    shared_docs = SharedDocs(workspace_root) if workspace_root is not None else None
    graph = StateGraph(GraphState)
    graph.add_node(ASK_TASKS, ask_tasks_node)
    graph.add_node(BUILD_WAYS, make_build_ways_node(model))
    graph.add_node(GUIDANCE_TRIGGER, guidance_trigger_node)
    graph.add_node(PLANNER, planner_node)
    graph.add_node(CONTEXT_ASSEMBLER, make_assembler_node(shared_docs=shared_docs))
    graph.add_node(ACTOR, make_actor_node(model, shared_docs=shared_docs))
    graph.add_node(VERIFIER, make_verifier_node(model))
    graph.add_node(LOOP_EXHAUSTED, loop_exhausted_node)

    graph.add_conditional_edges(START, route_from_start, END_MAP)
    graph.add_edge(ASK_TASKS, END)
    graph.add_conditional_edges(
        BUILD_WAYS,
        _after_build_ways,
        {GUIDANCE_TRIGGER: GUIDANCE_TRIGGER, END: END},
    )
    graph.add_edge(GUIDANCE_TRIGGER, END)
    graph.add_edge(PLANNER, END)
    # 主环：assembler→actor→verifier→（计数/双过/未清/清而未过）→END|PLANNER|LOOP_EXHAUSTED
    graph.add_edge(CONTEXT_ASSEMBLER, ACTOR)
    if model is None:
        # 05 骨架 CLI 无真模型：actor→END 直连（跳过 verifier），主环 inert 不挂死；
        # 真模型票接入后闭合 verifier 环。
        graph.add_edge(ACTOR, END)
    else:
        graph.add_edge(ACTOR, VERIFIER)
        graph.add_conditional_edges(
            VERIFIER,
            _after_verifier,
            {LOOP_EXHAUSTED: LOOP_EXHAUSTED, END: END, PLANNER: PLANNER},
        )
        graph.add_edge(LOOP_EXHAUSTED, END)

    # REPL 宿主始终带 checkpointer（无持久化就没有断点续跑）
    if checkpointer is None:
        checkpointer = InMemorySaver()
    return graph.compile(checkpointer=checkpointer)


@contextmanager
def sqlite_checkpointer(db_path: str | Path) -> Iterator[Any]:
    """磁盘断点持久化：进程退出后状态可查（票 L11『落盘可查』）。

    SqliteSaver 持有连接须显式关闭，故为上下文管理器形态。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()
