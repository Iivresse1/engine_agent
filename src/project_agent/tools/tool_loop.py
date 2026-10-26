"""工具定义与调用回路（17 票）：OpenAI 兼容 function schema + 五次工序编排。

形态（spec『工具执行回路』）：一轮内最多 `MAX_TOOL_ITERATIONS` 次工具往返——
定义 → 调模型 → 判定 → 执行 → 回灌，直到模型不再返回 `tool_calls`。

三条硬约束的落点：
1. **权限在构造期**：`tool_definitions(role)` 只给**该角色面内**的工具，模型
   看不到面外工具；`ToolRegistry.check` 是第二道（防模型幻觉造工具名）。
2. **工具错误不中断环**：deny / 异常 / 超限一律折成 `tool` 消息回灌。
3. **文本桥不删**：本模块只提供回路，调用方（actor）决定何时用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from project_agent.tools.decision import DecisionAction
from project_agent.tools.registry import ToolRegistry

#: 单轮工具往返封顶（超限转 round 交付并说明）
MAX_TOOL_ITERATIONS = 8

_STR = {"type": "string"}
_PATH = {"type": "string", "description": "相对项目根目录的路径（不得用绝对路径或 ..）"}

#: 工具名 → OpenAI function schema（description 面向模型，须说清"何时用"）
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "FileRead": {
        "description": "读取项目内某个文本文件的内容（带行号）。想看某文件写了什么时用。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": _PATH,
                "offset": {"type": "integer", "description": "起始行号（1-based，默认 1）"},
                "limit": {"type": "integer", "description": "最多读多少行（默认 2000）"},
            },
            "required": ["path"],
        },
    },
    "Glob": {
        "description": "按 glob 模式查找项目内的文件（如 'src/**/*.py'）。想知道有哪些文件时用。",
        "parameters": {
            "type": "object",
            "properties": {"pattern": {"type": "string", "description": "glob 模式"}},
            "required": ["pattern"],
        },
    },
    "Grep": {
        "description": "在项目内按正则搜索文件内容，返回 文件:行:内容。想定位某段代码/文字时用。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则表达式"},
                "path": {"type": "string", "description": "搜索范围（默认整个项目）"},
                "ignore_case": {"type": "boolean", "description": "是否忽略大小写"},
            },
            "required": ["pattern"],
        },
    },
    "FileWrite": {
        "description": "把内容全量写入项目内某文件（父目录自动创建，覆盖原内容）。新建文档时用。",
        "parameters": {
            "type": "object",
            "properties": {"path": _PATH, "content": {"type": "string", "description": "完整文件内容"}},
            "required": ["path", "content"],
        },
    },
    "FileEdit": {
        "description": "在项目内某文件里把 old 文本替换为 new（old 必须唯一命中）。改已有文档时优先用它。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": _PATH,
                "old": {"type": "string", "description": "待替换的原文（须唯一）"},
                "new": {"type": "string", "description": "替换后的新文本"},
            },
            "required": ["path", "old", "new"],
        },
    },
    "DocScaffold": {
        "description": "按当前构建方式一次性生成交付物骨架文件（已存在的会跳过，不覆盖）。",
        "parameters": {
            "type": "object",
            "properties": {
                "build_way": {"type": "string", "description": "构建方式 way2/way3/way4"},
                "path": {"type": "string", "description": "可选：放到哪个子目录"},
            },
            "required": ["build_way"],
        },
    },
    "NotepadAdd": {
        "description": "把一条笔记追加进项目 NOTES（记录错误猜想与经验教训）。",
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "一条笔记"}},
            "required": ["note"],
        },
    },
    "Shell": {
        "description": "执行一条 shell 命令（会过静态安全检查与人工审批档位）。查看环境、跑构建时用。",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "完整 shell 命令"}},
            "required": ["command"],
        },
    },
}


def tool_definitions(role: str, registry: ToolRegistry | None = None, *, extra: Sequence[str] = ()) -> list[dict[str, Any]]:
    """产出该角色面内的 OpenAI function schema 列表（面外工具不出现）。"""
    tool_registry = ToolRegistry() if registry is None else registry
    allowed = set(tool_registry.tools_for(role)) | set(extra)
    definitions: list[dict[str, Any]] = []
    for name in sorted(allowed):
        schema = TOOL_SCHEMAS.get(name)
        if schema is None:
            continue  # 面内有但无 schema 的工具（如 WebSearch）暂不暴露给模型
        definitions.append({"type": "function", "function": {"name": name, **schema}})
    return definitions


@dataclass
class ToolInvocation:
    """一次工具调用的记录（供 round payload 与审计）。"""

    tool: str
    arguments: dict[str, Any]
    result: str
    ok: bool


@dataclass
class LoopOutcome:
    """工具环的终局：模型终稿 + 本次调用记录 + 是否耗尽轮次。"""

    text: str
    invocations: list[ToolInvocation] = field(default_factory=list)
    exhausted: bool = False

    @property
    def summary(self) -> str:
        """一行回执（进 round payload，不刷屏）。"""
        if not self.invocations:
            return ""
        ok_count = sum(1 for item in self.invocations if item.ok)
        names = "、".join(sorted({item.tool for item in self.invocations}))
        tail = "（已达工具轮次上限）" if self.exhausted else ""
        return f"工具调用 {len(self.invocations)} 次（成功 {ok_count}）：{names}{tail}"


#: 模型调用签名：messages + tools → 带 tool_calls 的消息对象
CompleteFn = Callable[[Sequence[Mapping[str, Any]], list[dict[str, Any]]], Any]


def _tool_call_parts(call: Any) -> tuple[str, dict[str, Any], str]:
    """从不同形态的 tool_call（dict / 对象）取 (name, args, id)。"""
    if isinstance(call, Mapping):
        name = str(call.get("name") or "")
        raw_args = call.get("args") or call.get("arguments") or {}
        call_id = str(call.get("id") or "")
    else:
        name = str(getattr(call, "name", "") or "")
        raw_args = getattr(call, "args", None) or getattr(call, "arguments", None) or {}
        call_id = str(getattr(call, "id", "") or "")
    if isinstance(raw_args, str):
        import json

        try:
            raw_args = json.loads(raw_args)
        except ValueError:
            raw_args = {}
    arguments = dict(raw_args) if isinstance(raw_args, Mapping) else {}
    return name, arguments, call_id


@dataclass
class ToolLoop:
    """工具调用环：注入模型调用 + 工具执行，编排五次工序。

    测试可注入 `complete`（返回带 tool_calls 的假消息）与 `runner`
    （`(tool, arguments) -> ToolResult | str`），无需真模型。

    `runner` 是**已绑定工作区**的执行函数（生产环境由调用方用
    `functools.partial(execute, workspace_root)` 绑定），因此本类不持 root。
    """

    role: str
    runner: Callable[[str, Mapping[str, Any]], Any]
    registry: ToolRegistry = field(default_factory=ToolRegistry)
    max_iterations: int = MAX_TOOL_ITERATIONS

    def run(
        self,
        complete: CompleteFn,
        messages: list[Mapping[str, Any]],
    ) -> LoopOutcome:
        """驱动回路直到模型不再请求工具（或轮次耗尽）。"""
        definitions = tool_definitions(self.role, self.registry)
        history: list[Mapping[str, Any]] = list(messages)
        invocations: list[ToolInvocation] = []

        for _ in range(self.max_iterations):
            reply = complete(history, definitions)
            calls = list(getattr(reply, "tool_calls", None) or [])
            if not calls:
                return LoopOutcome(text=str(getattr(reply, "text", "") or ""), invocations=invocations)

            # 把模型这轮的 tool_calls 塞回历史（OpenAI 协议要求）
            history = [
                *history,
                {
                    "role": "assistant",
                    "content": str(getattr(reply, "text", "") or ""),
                    "tool_calls": [
                        {
                            "id": _tool_call_parts(call)[2],
                            "type": "function",
                            "function": {
                                "name": _tool_call_parts(call)[0],
                                "arguments": json.dumps(_tool_call_parts(call)[1], ensure_ascii=False),
                            },
                        }
                        for call in calls
                    ],
                },
            ]

            for call in calls:
                name, arguments, call_id = _tool_call_parts(call)
                content, ok = self._invoke(name, arguments)
                invocations.append(
                    ToolInvocation(tool=name, arguments=dict(arguments), result=content, ok=ok)
                )
                history = [
                    *history,
                    {"role": "tool", "tool_call_id": call_id, "content": content},
                ]

        return LoopOutcome(text="", invocations=invocations, exhausted=True)

    def _invoke(self, tool: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        """单次判定 + 执行：deny 与异常都折成字符串回灌（环不中断）。"""
        target = arguments.get("path")
        decision = self.registry.check(self.role, tool, str(target) if target else None)
        if decision.action is DecisionAction.DENY:
            return f"错误：{decision.reason}", False
        try:
            result = self.runner(tool, arguments)
        except Exception as exc:  # noqa: BLE001 - 工具异常一律回灌，环不中断
            return f"错误：{tool} 执行失败（{type(exc).__name__}: {exc}）", False
        if hasattr(result, "content"):
            return str(result.content), bool(getattr(result, "ok", True))
        return str(result), True


__all__ = [
    "MAX_TOOL_ITERATIONS",
    "TOOL_SCHEMAS",
    "LoopOutcome",
    "ToolInvocation",
    "ToolLoop",
    "tool_definitions",
]
