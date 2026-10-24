"""统一输入协议：所有断点输入都是自由文本，按断点协议表融合进目标私有 key。"""

from __future__ import annotations

from typing import Any, Mapping

from langchain_core.messages import HumanMessage

from project_agent.protocol import (
    BREAKPOINT_PROTOCOL,
    Fusion,
    Role,
    TurnEndReason,
)

MAINLINE_KEY = "actor_messages"

_PRIVATE_KEY_BY_ROLE: dict[Role, str] = {
    Role.ACTOR: "actor_messages",
    Role.DEMO: "demo_messages",
}


def _reason_of(state: Mapping[str, Any]) -> TurnEndReason | None:
    raw = state.get("turn_end_reason")
    if raw is None:
        return None
    try:
        return TurnEndReason(raw)
    except ValueError:
        return None


def fusion_update(
    state: Mapping[str, Any], text: str
) -> dict[str, list[HumanMessage]]:
    """把用户自由文本融合成图输入更新（恰好指向一个私有 key）。"""
    reason = _reason_of(state)
    if reason is None:
        return {MAINLINE_KEY: [HumanMessage(content=text)]}

    spec = BREAKPOINT_PROTOCOL[reason]
    if spec.fusion is Fusion.TERMINAL:
        return {}

    key = MAINLINE_KEY
    if spec.fusion is Fusion.ASKER:
        raw_role = state.get("awaiting_input_from", "")
        try:
            role = Role(raw_role)
        except ValueError:
            role = Role.ACTOR
        key = _PRIVATE_KEY_BY_ROLE.get(role, MAINLINE_KEY)
    return {key: [HumanMessage(content=text)]}
