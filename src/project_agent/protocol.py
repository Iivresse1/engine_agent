"""断点协议：turn_end_reason × payload 受控形状 × 融合目标（spec v1.1『状态契约』）。

表即契约：BREAKPOINT_PROTOCOL 是 REPL↔主图主接缝的权威定义，
测试逐行断言本表与 spec 断点协议表一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class TurnEndReason(str, Enum):
    ROUND = "round"
    QUESTION = "question"
    CHOICE_BUILD_WAY = "choice:build_way"
    CHOICE_PROPOSAL = "choice:proposal"
    DOCS_DONE = "docs_done"
    LOOP_EXHAUSTED = "loop_exhausted"
    FINISHED = "finished"


class Fusion(str, Enum):
    MAINLINE = "mainline"            # 融合进主线角色私有历史
    ASKER = "asker"                  # 融合进 awaiting_input_from 指向的私有 key
    RESOLUTION = "resolution"        # 由决议节点解释后写仪表盘字段
    FREE_MAINLINE = "free_mainline"  # 自由融合（人工接管语境）
    TERMINAL = "terminal"            # 终态，不再融合


@dataclass(frozen=True)
class BreakpointSpec:
    fusion: Fusion
    required_payload_fields: tuple[str, ...] = ()


BREAKPOINT_PROTOCOL: dict[TurnEndReason, BreakpointSpec] = {
    TurnEndReason.ROUND: BreakpointSpec(
        Fusion.MAINLINE, ("round_output", "todo_board")
    ),
    TurnEndReason.QUESTION: BreakpointSpec(
        Fusion.ASKER, ("question_text", "options", "asker")
    ),
    TurnEndReason.CHOICE_BUILD_WAY: BreakpointSpec(
        Fusion.RESOLUTION, ("options", "recommendation", "recommendation_reason")
    ),
    TurnEndReason.CHOICE_PROPOSAL: BreakpointSpec(
        Fusion.RESOLUTION, ("proposal_summaries",)
    ),
    TurnEndReason.DOCS_DONE: BreakpointSpec(
        Fusion.RESOLUTION, ("deliverables_overview", "options")
    ),
    TurnEndReason.LOOP_EXHAUSTED: BreakpointSpec(
        Fusion.FREE_MAINLINE, ("help_text",)
    ),
    TurnEndReason.FINISHED: BreakpointSpec(
        Fusion.TERMINAL, ("delivery_paths",)
    ),
}

_LIST_FIELDS = frozenset({"options", "proposal_summaries", "todo_board"})
_DICT_FIELDS = frozenset({"delivery_paths"})


class PayloadError(Exception):
    """断点 payload 违反受控形状。"""


def validate_payload(reason: TurnEndReason, payload: Mapping[str, Any]) -> dict[str, Any]:
    """校验并返回规范化的 payload；违反受控形状时抛 PayloadError。"""
    spec = BREAKPOINT_PROTOCOL[reason]
    data = dict(payload)

    missing = [field for field in spec.required_payload_fields if field not in data]
    if missing:
        raise PayloadError(f"{reason.value} 缺少必填字段: {missing}")

    unknown = set(data) - set(spec.required_payload_fields)
    if unknown:
        raise PayloadError(f"{reason.value} 出现协议外字段: {sorted(unknown)}")

    for field in spec.required_payload_fields:
        value = data[field]
        if field in _LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise PayloadError(f"{reason.value}.{field} 应为 list[str]")
        elif field in _DICT_FIELDS:
            if not isinstance(value, dict):
                raise PayloadError(f"{reason.value}.{field} 应为 dict")
        elif not isinstance(value, str):
            raise PayloadError(f"{reason.value}.{field} 应为 str")

    return data
