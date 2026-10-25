"""协议消息层（UX-2，spec v2.1『协议消息层』）：前后端唯一主接缝的纯翻译层。

表即契约：`DOWN_MESSAGES` / `UP_MESSAGES` 是 spec 消息表的权威定义，测试逐行
断言本表与 spec 一致。本模块只做两件事——形状校验与折叠渲染：

- `encode(kind, **fields)`：构造下行信封，字段与表逐字对齐（缺/多即 `MessageError`）
- `decode(data)`：校验并归一化上行消息（`type` 查表一次完成）
- `default_rendering(kind, payload)`：把任意下行消息折成终端行（后端裸终端降级）

红线：本层零业务逻辑、零图依赖——不 import 任何节点/图/模型模块，否则即倒退
（ADR-0005 接缝预算：前端引入只新增这一条缝，且缝的这一侧不许反向依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class MessageError(Exception):
    """消息违反受控形状（缺字段 / 多字段 / 错类型 / 未知 type）。"""


@dataclass(frozen=True)
class MessageSpec:
    """一条协议消息的受控形状。`fields` 为必填字段名，按 spec 表列序。"""

    fields: tuple[str, ...]


# 下行：后端 → 前端（展示用；前端不解析业务含义）
DOWN_MESSAGES: dict[str, MessageSpec] = {
    "ready": MessageSpec(("banner", "opening_prompt")),
    "prompt": MessageSpec(("awaiting",)),
    "round_end": MessageSpec(("reason", "payload", "lines")),
    "notice": MessageSpec(("text",)),
    "teach_page": MessageSpec(("path", "round")),
    "farewell": MessageSpec(("text",)),
}

# 上行：前端 → 后端（输入用；纯文本，决议解释权在后端）
UP_MESSAGES: dict[str, MessageSpec] = {
    "input": MessageSpec(("text",)),
    "quit": MessageSpec(()),
}

_LIST_FIELDS = frozenset({"lines"})
_DICT_FIELDS = frozenset({"payload"})
_INT_FIELDS = frozenset({"round"})


def _check_fields(kind: str, spec: MessageSpec, data: Mapping[str, Any]) -> None:
    missing = [field for field in spec.fields if field not in data]
    if missing:
        raise MessageError(f"{kind} 缺少必填字段: {missing}")
    unknown = set(data) - set(spec.fields)
    if unknown:
        raise MessageError(f"{kind} 出现协议外字段: {sorted(unknown)}")
    for field in spec.fields:
        value = data[field]
        if field in _LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise MessageError(f"{kind}.{field} 应为 list[str]")
        elif field in _DICT_FIELDS:
            if not isinstance(value, dict):
                raise MessageError(f"{kind}.{field} 应为 dict")
        elif field in _INT_FIELDS:
            if not isinstance(value, int) or isinstance(value, bool):
                raise MessageError(f"{kind}.{field} 应为 int")
        elif not isinstance(value, str):
            raise MessageError(f"{kind}.{field} 应为 str")


def encode(kind: str, **fields: Any) -> dict[str, Any]:
    """构造下行消息信封：`{"type": kind, **fields}`，形状严格对齐 `DOWN_MESSAGES`。"""
    spec = DOWN_MESSAGES.get(kind)
    if spec is None:
        raise MessageError(f"未知下行消息类型: {kind!r}")
    _check_fields(kind, spec, {**fields})
    return {"type": kind, **fields}


def decode(data: Mapping[str, Any]) -> dict[str, Any]:
    """校验上行消息：`type` 查表一次完成，字段缺多皆为 `MessageError`。"""
    if not isinstance(data, Mapping):
        raise MessageError("消息必须是 mapping")
    kind = data.get("type")
    spec = UP_MESSAGES.get(kind) if isinstance(kind, str) else None
    if spec is None:
        raise MessageError(f"未知上行消息类型: {kind!r}")
    fields = {key: value for key, value in data.items() if key != "type"}
    _check_fields(kind, spec, fields)
    return {"type": kind, **fields}


def default_rendering(kind: str, payload: Mapping[str, Any]) -> list[str]:
    """把一条下行消息折成终端行——后端裸终端降级路径（前端未接线时的唯一出路）。

    纯函数，无副作用；`ready` 依 spec 输出横幅与空行 + 开场提示两段式。
    """
    if kind == "ready":
        return [str(payload.get("banner") or ""), "", str(payload.get("opening_prompt") or "")]
    if kind == "prompt":
        awaiting = str(payload.get("awaiting") or "")
        return [f"等待输入 · {awaiting}"] if awaiting else []
    if kind == "round_end":
        reason = str(payload.get("reason") or "")
        lines = payload.get("lines")
        head = f"断点 · {reason}" if reason else "断点"
        body = list(lines) if isinstance(lines, list) else []
        return [head, *body]
    if kind == "notice":
        return [str(payload.get("text") or "")]
    if kind == "teach_page":
        return [f"教学页已生成：{payload.get('path') or ''}"]
    if kind == "farewell":
        return [str(payload.get("text") or "")]
    raise MessageError(f"未知下行消息类型: {kind!r}")


def round_end_message(reason: str, payload: Mapping[str, Any], lines: list[str]) -> dict[str, Any]:
    """断点消息的便捷构造器：`round_end` 三字段一次写齐（REPL 与未来服务端共用）。"""
    return encode("round_end", reason=reason, payload=dict(payload), lines=list(lines))
