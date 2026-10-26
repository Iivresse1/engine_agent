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
    docs_done_node,
    guidance_trigger_node,
    loop_exhausted_node,
    make_actor_node,
    make_assembler_node,
    make_build_ways_node,
    make_check_node,
    make_demo_agent_node,
    make_finalizer_node,
    make_proposals_node,
    make_verifier_node,
    planner_node,
    with_compression,
)
from project_agent.routing import (
    ACTOR,
    ASK_TASKS,
    BUILD_WAYS,
    CHECK_PROPER_OUTPUT,
    CONTEXT_ASSEMBLER,
    DEMO_AGENT,
    DOCS_DONE,
    END_MAP,
    FINALIZER,
    GUIDANCE_TRIGGER,
    LOOP_EXHAUSTED,
    PLANNER,
    PROPOSALS,
    VERIFIER,
    _after_check,
    _after_demo,
    _after_docs_done,
    _after_verifier,
    route_from_start,
)
from project_agent.shared_docs import SharedDocs
from project_agent.state import GraphState


def new_thread_id() -> str:
    return uuid.uuid4().hex


def _after_build_ways(state: Mapping[str, Any]) -> str:
    """build_ways 出口：build_way 已设→guidance_trigger；未设（choice 断点）→END。"""
    return GUIDANCE_TRIGGER if state.get("build_way") else END


def build_graph(
    checkpointer: Any = None,
    model: Any = None,
    workspace_root: Path | None = None,
    cheap_model: Any = None,
    store: Any = None,
    link_fetch: Any = None,
) -> Any:
    """workspace_root 非 None → SharedDocs(workspace_root) 同源注入
    assembler 与 actor 两工厂（09：assembler 读 notepad 切片/版本门，
    actor 每轮生成物带【R#】落盘 + Notepad 指令；06：同签名单注入 actor）；
    None → 不注入（05 行为，cli.py 零改动：骨架无模型本就不落盘；
    真模型票接线时传 cwd）。

    08：cheap_model 非 None → actor/verifier/assembler 三节点包
    with_compression（Q54 模型调用前统一压缩检查；planner 无 LLM 调用
    不挂）；11 票补第四挂点 DEMO_AGENT（读 demo_messages 私有历史）。
    None → 裸节点（基线零回归）。

    12：store 非 None → 传 finalizer 工厂（final_report 入 Store 跨线程
    长期记忆）；None → finalizer 零 Store 写（轻实现默认）。langgraph
    Store 正式接入留接线票。"""
    shared_docs = SharedDocs(workspace_root) if workspace_root is not None else None
    graph = StateGraph(GraphState)
    graph.add_node(ASK_TASKS, ask_tasks_node)
    graph.add_node(BUILD_WAYS, make_build_ways_node(model))
    graph.add_node(GUIDANCE_TRIGGER, guidance_trigger_node)
    # 07：way4 三方案并行节点（model=None 走静态兜底三案）
    graph.add_node(PROPOSALS, make_proposals_node(model))
    graph.add_node(PLANNER, planner_node)
    # 09：assembler 工厂化（五段组装+版本门+工具子集）；07 的 way4 脚手架
    # 提示已织入工厂内层；08：cheap_model 时包 with_compression。
    graph.add_node(
        CONTEXT_ASSEMBLER,
        with_compression(
            make_assembler_node(shared_docs=shared_docs),
            cheap_model=cheap_model,
            shared_docs=shared_docs,
        )
        if cheap_model is not None
        else make_assembler_node(shared_docs=shared_docs),
    )
    graph.add_node(
        ACTOR,
        with_compression(
            make_actor_node(model, shared_docs=shared_docs, link_fetch=link_fetch),
            cheap_model=cheap_model,
            shared_docs=shared_docs,
        )
        if cheap_model is not None
        else make_actor_node(model, shared_docs=shared_docs, link_fetch=link_fetch),
    )
    graph.add_node(
        VERIFIER,
        with_compression(
            make_verifier_node(model),
            cheap_model=cheap_model,
            shared_docs=shared_docs,
        )
        if cheap_model is not None
        else make_verifier_node(model),
    )
    graph.add_node(LOOP_EXHAUSTED, loop_exhausted_node)
    # 11：docs_done 决议断点（纯代码）+ DemoAgent（生成不运行；cheap_model
    # 非 None 时第四挂点——压缩检查读 demo_messages 私有历史）
    graph.add_node(DOCS_DONE, docs_done_node)
    demo_node = make_demo_agent_node(model, shared_docs=shared_docs)
    if cheap_model is not None:
        demo_node = with_compression(
            demo_node,
            cheap_model=cheap_model,
            shared_docs=shared_docs,
            messages_key="demo_messages",
        )
    graph.add_node(DEMO_AGENT, demo_node)
    # 12：finalizer 收尾整理（final_report + Store 存取）+ check_proper_output
    # 终检管线（run_final_check 双份交付）
    graph.add_node(FINALIZER, make_finalizer_node(model, store=store, shared_docs=shared_docs))
    graph.add_node(
        CHECK_PROPER_OUTPUT,
        make_check_node(model, shared_docs=shared_docs),
    )

    graph.add_conditional_edges(START, route_from_start, END_MAP)
    graph.add_edge(ASK_TASKS, END)
    graph.add_edge(PROPOSALS, END)  # 07：断点收轮（choice:proposal）
    graph.add_conditional_edges(
        BUILD_WAYS,
        _after_build_ways,
        {GUIDANCE_TRIGGER: GUIDANCE_TRIGGER, END: END},
    )
    graph.add_edge(GUIDANCE_TRIGGER, END)
    graph.add_edge(PLANNER, END)
    # 11→12：docs_done 三态出口——building 同轮接 DEMO_AGENT；
    # skipped/done → FINALIZER（12 改向：原 END 边被替换）；未决收轮
    graph.add_conditional_edges(
        DOCS_DONE,
        _after_docs_done,
        {DEMO_AGENT: DEMO_AGENT, FINALIZER: FINALIZER, END: END},
    )
    # 11→12：demo 出口——计数封顶优先，否则接 FINALIZER（12 改向：
    # 原 END 收轮边被替换——demo 完成后进终检）
    graph.add_conditional_edges(
        DEMO_AGENT,
        _after_demo,
        {LOOP_EXHAUSTED: LOOP_EXHAUSTED, FINALIZER: FINALIZER},
    )
    # 12：终检链——FINALIZER→CHECK_PROPER_OUTPUT 顺序边；check 出口
    # 三态（output_clean 真→END（finished 断点已写）；假且环计数<5→
    # PLANNER（回环修复）；==5→LOOP_EXHAUSTED）
    graph.add_edge(FINALIZER, CHECK_PROPER_OUTPUT)
    graph.add_conditional_edges(
        CHECK_PROPER_OUTPUT,
        _after_check,
        {END: END, PLANNER: PLANNER, LOOP_EXHAUSTED: LOOP_EXHAUSTED},
    )
    graph.add_edge(LOOP_EXHAUSTED, END)
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
