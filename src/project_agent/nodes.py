"""01 票骨架节点：ask_tasks / build_ways / placeholder。

全部可重入：已写字段不再改写（断点续跑下轮重进不重复副作用）。
02 票将把 build_ways 升级为 choice:build_way 断点流。
"""

from __future__ import annotations

from typing import Any, Mapping

from langchain_core.messages import HumanMessage

from project_agent.protocol import TurnEndReason, validate_payload


def _latest_human_text(state: Mapping[str, Any]) -> str | None:
    for msg in reversed(list(state.get("actor_messages") or [])):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _round_end(round_output: str, state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """写 round 断点：轮产出 + todo 板（spec 断点协议表 round 行 payload）。"""
    payload = validate_payload(
        TurnEndReason.ROUND,
        {"round_output": round_output, "todo_board": _todo_board(state)},
    )
    return {"turn_end_reason": TurnEndReason.ROUND.value, "turn_end_payload": payload}


def _todo_board(state: Mapping[str, Any] | None) -> list[str]:
    """三态 todo 板渲染（01 骨架：工作流级 todos 通常为空 → 空板）。"""
    board: list[str] = []
    for item in (state or {}).get("todos") or []:
        if isinstance(item, dict):
            content = str(item.get("content", ""))
            status = str(item.get("status", "pending"))
            board.append(f"{status}: {content}")
    return board


def ask_tasks_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """把首个自由输入记为任务简报（一次写定，再进不改写）。"""
    if state.get("task_brief"):
        return {}
    text = _latest_human_text(state)
    if not text:
        return {}
    return {"task_brief": text, **_round_end(f"任务简报已记录：{text}", state)}


_BUILD_WAY_KEYWORDS: list[tuple[str, str]] = [
    ("完整", "way4"),
    ("简化", "way3"),
    ("轻", "way2"),
    ("对话", "way1"),
]


def _interpret_build_way(text: str | None) -> str | None:
    if not text:
        return None
    for keyword, way in _BUILD_WAY_KEYWORDS:
        if keyword in text:
            return way
    return None


def build_ways_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """关键词解释构建方式（02 票换成 choice:build_way 断点 + 决议节点）。

    协议约束：每条可达路径必须写新断点——解释不了输入时以 fresh round_end
    提示重述，绝不静默返回（否则上轮 turn_end 残留会被再次渲染）。
    """
    if state.get("build_way"):
        return {}
    way = _interpret_build_way(_latest_human_text(state))
    if way is None:
        return _round_end("未识别构建方式。01 骨架关键词：完整 / 简化 / 轻 / 对话。", state)
    return {"build_way": way, **_round_end(f"构建方式已定：{way}", state)}


def placeholder_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """default 相位占位：输入已融合、状态已保存，后续相位随票落位。"""
    return _round_end("占位：该相位未实现（01 票骨架）。输入已融合，状态已保存。", state)
