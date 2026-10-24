"""主工作流图：START → 入口路由（纯代码相位重建）→ 骨架节点 → END。

一轮 = 一次完整图执行；END 即断点（checkpointer 落盘、控制权交还 REPL 宿主）。
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from project_agent.nodes import ask_tasks_node, build_ways_node, placeholder_node
from project_agent.routing import ASK_TASKS, BUILD_WAYS, PLACEHOLDER, route_from_start
from project_agent.state import GraphState


def new_thread_id() -> str:
    return uuid.uuid4().hex


def build_graph(checkpointer: Any = None) -> Any:
    graph = StateGraph(GraphState)
    graph.add_node(ASK_TASKS, ask_tasks_node)
    graph.add_node(BUILD_WAYS, build_ways_node)
    graph.add_node(PLACEHOLDER, placeholder_node)

    graph.add_conditional_edges(
        START,
        route_from_start,
        {ASK_TASKS: ASK_TASKS, BUILD_WAYS: BUILD_WAYS, PLACEHOLDER: PLACEHOLDER},
    )
    graph.add_edge(ASK_TASKS, END)
    graph.add_edge(BUILD_WAYS, END)
    graph.add_edge(PLACEHOLDER, END)

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
