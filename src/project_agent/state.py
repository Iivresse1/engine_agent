"""图状态：仪表盘（受控字段）+ 私有 key（隔离红线落点）。

仪表盘只收 spec v1.1『仪表盘字段表』钉定的字段，任何消息转储不得入内；
角色消息历史全部走私有 key（add_messages 追加式 reducer）。
"""

from __future__ import annotations

from typing import Annotated, Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class Dashboard(TypedDict, total=False):
    task_brief: str
    build_way: str
    guidance_mode: str
    user_mode: str
    guidance_pref: str
    decision_mode: str
    skill_packs: list[str]
    proposal_set: list[Any]
    selected_proposal: int
    todos: list[Any]
    todos_all_completed: bool
    task_complete: bool
    is_docs_finished: bool
    output_clean: bool
    main_loop_count: int
    demo_loop_count: int
    final_check_loop_count: int
    demo_phase: str
    round_summary: str
    notes_version: int
    guidance_read_version: int
    current_scope: str
    turn_end_reason: str
    turn_end_payload: dict[str, Any]
    awaiting_input_from: str
    final_report: str


class GraphState(Dashboard, total=False):
    actor_messages: Annotated[list[Any], add_messages]
    demo_messages: Annotated[list[Any], add_messages]
    assembled_context: dict[str, Any]
    # 决议通道：无 reducer 整覆写——融合端 [*existing, text] 追加、决议节点返回 [] 清空
    resolution_inputs: list[str]
