"""shell 审批协议：ApprovalRequest/ApprovalResult + 同步审批回调。

ADR-0001 例外边界：审批在 REPL 宿主层同步完成——不进图、不落 turn_end_reason、
不 import langgraph/nodes/graph/repl（由 AST 测试钉死）。

不保证（调研 §10.3）：回调是同步阻塞模型，不支持异步审批流；审批回调本身
的呈现（问题文案/选项渲染）属 REPL 宿主职责，本层只传结构化数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ApprovalRequest:
    """审批请求：命中 ask 的命令 + 来源规则 + 原因（供宿主渲染问题）。"""

    command: str
    segment: str
    rule_id: str
    reason: str


@dataclass(frozen=True)
class ApprovalResult:
    """审批结果：approved + 可选备注（拒绝原因等，回传给 agent）。"""

    approved: bool
    note: str = ""


class ShellApprovalCallback(Protocol):
    """同步阻塞审批回调：REPL 宿主实现（终端提问 → 用户答 y/n）。"""

    def __call__(self, request: ApprovalRequest) -> ApprovalResult: ...


class TerminalApprovalCallback:
    """终端最小桩：用 config.IO 协议问一行 y/n（生产宿主可替换）。"""

    def __init__(self, io) -> None:
        self._io = io

    def __call__(self, request: ApprovalRequest) -> ApprovalResult:
        self._io.write_line(
            f"[shell 审批] {request.command}（规则 {request.rule_id}：{request.reason}）"
        )
        self._io.write_line("批准执行？(y/n)")
        line = self._io.read_line()
        answer = (line or "").strip().lower()
        if answer in {"y", "yes"}:
            return ApprovalResult(approved=True)
        return ApprovalResult(approved=False, note="用户拒绝")


__all__ = [
    "ApprovalRequest",
    "ApprovalResult",
    "ShellApprovalCallback",
    "TerminalApprovalCallback",
]
