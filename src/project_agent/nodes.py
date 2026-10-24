"""骨架节点：ask_tasks / build_ways（choice:build_way 断点流）/ placeholder。

全部可重入：已写字段不再改写（断点续跑下轮重进不重复副作用）。
build_ways 由 make_build_ways_node(model) 工厂构造——model=None 走静态推荐。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from langchain_core.messages import HumanMessage

from project_agent.protocol import Role, TurnEndReason, validate_payload


# 四种构建方式（GLOSSARY『build_ways』）：标签即 choice payload 的 options
BUILD_WAY_OPTIONS: list[str] = ["对话", "轻 grill", "简化文档", "完整文档"]
_WAY_BY_LABEL: dict[str, str] = {
    "对话": "way1",
    "轻 grill": "way2",
    "简化文档": "way3",
    "完整文档": "way4",
}

# 静态默认（model=None 或模型输出垃圾）
_STATIC_RECOMMENDATION = "简化文档"
_STATIC_REASON = "个人作品有沉淀不臃肿"


def _STATIC_RECOMMENDATION_LABEL() -> str:
    return _STATIC_RECOMMENDATION

# 解释引擎关键词序（前缀优先防误吞）
_BUILD_WAY_KEYWORDS: list[tuple[str, str]] = [
    ("完整", "way4"),
    ("简化", "way3"),
    ("轻", "way2"),
    ("对话", "way1"),
    ("聊天", "way1"),
]

# 序号匹配：裸 ^[\W_]*([1-9])[\W_]*$ 或语境 (?:第|选项|方式|选)\s*([1-9])
# \W 不含汉字——"做个 2048 游戏"这类自由文本不会误中。
_BARE_INDEX = re.compile(r"^[\W_]*([1-9])[\W_]*$")
_CONTEXTUAL_INDEX = re.compile(r"(?:第|选项|方式|选)\s*([1-9])")


def _interpret_build_way(text: str | None, recommended: str | None = None) -> str | None:
    """解释自由文本 → way1–way4；解释不了返回 None。

    优先级：wayN 子串直配 → 序号（裸/语境）→ 关键词 → "推荐"按推荐。
    """
    if not text:
        return None
    lowered = text.lower()
    for n in range(1, 5):
        if f"way{n}" in lowered:
            return f"way{n}"
    m = _BARE_INDEX.match(text) or _CONTEXTUAL_INDEX.search(text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 4:
            return f"way{n}"
    for keyword, way in _BUILD_WAY_KEYWORDS:
        if keyword in text:
            return way
    if "推荐" in text and recommended is not None:
        way = _WAY_BY_LABEL.get(recommended)
        if way is not None:
            return way
    return None


def _choice_breakpoint(
    recommendation: str, reason: str
) -> dict[str, Any]:
    payload = validate_payload(
        TurnEndReason.CHOICE_BUILD_WAY,
        {
            "options": list(BUILD_WAY_OPTIONS),
            "recommendation": recommendation,
            "recommendation_reason": reason[:20],
        },
    )
    return {"turn_end_reason": TurnEndReason.CHOICE_BUILD_WAY.value, "turn_end_payload": payload}


def _latest_human_text(state: Mapping[str, Any]) -> str | None:
    for msg in reversed(list(state.get("actor_messages") or [])):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _first_human_text(state: Mapping[str, Any]) -> str | None:
    for msg in list(state.get("actor_messages") or []):
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


def make_build_ways_node(model: Any = None):
    """build_ways 节点工厂：choice:build_way 断点流 + 决议通道消费。

    - build_way 已设 → {}（可重入零副作用）
    - resolution_inputs 非空 → 消费 pending[-1]：解释成功 → 写 build_way +
      清空通道 + round_end("构建方式已定：wayN")；不可解释 → 清空 + 复用上轮
      turn_end_payload（校验通过才复用）重发 choice——零重复 ModelClient 调用
    - 无 pending → 发 choice 断点：model 驱动推荐或静态默认
    """

    def _recommended_from_payload(payload: Any) -> str | None:
        if not isinstance(payload, Mapping):
            return None
        value = payload.get("recommendation")
        return value if isinstance(value, str) else None

    def _model_recommendation(state: Mapping[str, Any], config: Any) -> tuple[str, str]:
        brief = str(state.get("task_brief") or "")
        user_mode = str(state.get("user_mode") or "")
        prompt = (
            f"任务简报：{brief}\n"
            f"用户编程基础：{user_mode}\n"
            "四种构建方式：1=对话 2=轻 grill 3=简化文档 4=完整文档\n"
            "推荐其一并给一句话理由（≤20 字）。输出格式：选择|理由"
        )
        thread_id = ""
        if isinstance(config, Mapping):
            configurable = config.get("configurable") or {}
            if isinstance(configurable, Mapping):
                thread_id = str(configurable.get("thread_id") or "")
        result = model.complete(
            [{"role": "user", "content": prompt}],
            role=Role.ACTOR.value,
            thread_id=thread_id,
        )
        text = str(result.text)
        choice, _, reason = text.partition("|")
        way = _interpret_build_way(choice.strip())
        if way is None:
            return _STATIC_RECOMMENDATION_LABEL(), _STATIC_REASON
        label = _LABEL_BY_WAY[way]
        reason = reason.strip() or _STATIC_REASON
        return label, reason

    def build_ways_node(
        state: Mapping[str, Any], config: Optional[Mapping[str, Any]] = None
    ) -> dict[str, Any]:
        if state.get("build_way"):
            return {}

        pending = state.get("resolution_inputs") or []
        if pending:
            text = str(pending[-1])
            recommended = _recommended_from_payload(state.get("turn_end_payload"))
            way = _interpret_build_way(text, recommended=recommended)
            if way is not None:
                return {
                    "build_way": way,
                    "resolution_inputs": [],
                    **_round_end(f"构建方式已定：{way}", state),
                }
            # 不可解释：清空通道 + 复用上轮 payload 重发 choice（可重入零副作用）
            last_payload = state.get("turn_end_payload")
            reuse = _recommended_from_payload(last_payload) is not None
            if reuse and isinstance(last_payload, Mapping):
                try:
                    payload = validate_payload(
                        TurnEndReason.CHOICE_BUILD_WAY, dict(last_payload)
                    )
                except Exception:
                    payload = None
            else:
                payload = None
            if payload is not None:
                return {
                    "resolution_inputs": [],
                    "turn_end_reason": TurnEndReason.CHOICE_BUILD_WAY.value,
                    "turn_end_payload": payload,
                }
            return {"resolution_inputs": [], **_static_choice()}

        if model is not None:
            recommendation, reason = _model_recommendation(state, config)
        else:
            recommendation, reason = _STATIC_RECOMMENDATION, _STATIC_REASON
        return _choice_breakpoint(recommendation, reason)

    return build_ways_node


def _static_choice() -> dict[str, Any]:
    return _choice_breakpoint(_STATIC_RECOMMENDATION, _STATIC_REASON)


_LABEL_BY_WAY: dict[str, str] = {way: label for label, way in _WAY_BY_LABEL.items()}


def placeholder_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """default 相位占位：输入已融合、状态已保存，后续相位随票落位。"""
    return _round_end("占位：该相位未实现（01 票骨架）。输入已融合，状态已保存。", state)
