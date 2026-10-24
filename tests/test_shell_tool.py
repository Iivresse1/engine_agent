"""ShellTool 执行路径：ask→审批→执行、deny 零副作用、allow 零回调、AST 边界钉死。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from project_agent.tools.approval import (
    ApprovalRequest,
    ApprovalResult,
    TerminalApprovalCallback,
)
from project_agent.tools.knobs import ShellKnobs
from project_agent.tools.shell_policy import ShellPolicy
from project_agent.tools.shell_tool import ShellPermissionDenied, ShellTool
from tests.doubles.fake_shell import RecordingShell
from tests.doubles.scripted_io import ScriptedIO

SRC_TOOLS = Path(__file__).resolve().parents[1] / "src" / "project_agent" / "tools"


def _policy() -> ShellPolicy:
    return ShellPolicy(knobs=ShellKnobs(), workspace_root="D:/ws")


class StubApproval:
    """可编程审批桩：预置结果 + 记录收到的请求。"""

    def __init__(self, approved: bool, note: str = "") -> None:
        self.approved = approved
        self.note = note
        self.requests: list[ApprovalRequest] = []

    def __call__(self, request: ApprovalRequest) -> ApprovalResult:
        self.requests.append(request)
        return ApprovalResult(approved=self.approved, note=self.note)


# ---- ask → 审批通过 → 执行 ----

def test_ask_approved_runs_and_returns_output():
    shell = RecordingShell(outputs={"git clone https://github.com/u/r.git": "cloned"})
    approval = StubApproval(approved=True)
    tool = ShellTool(policy=_policy(), approval=approval, shell_runner=shell)
    out = tool.run("git clone https://github.com/u/r.git")
    assert out == "cloned"
    assert shell.calls == ["git clone https://github.com/u/r.git"]
    assert len(approval.requests) == 1
    request = approval.requests[0]
    assert request.rule_id == "whitelist.ask"
    assert request.reason
    assert request.command == "git clone https://github.com/u/r.git"


# ---- ask → 用户拒绝 → PermissionError，无副作用 ----

def test_ask_denied_raises_and_no_side_effect():
    shell = RecordingShell()
    approval = StubApproval(approved=False, note="不想要")
    tool = ShellTool(policy=_policy(), approval=approval, shell_runner=shell)
    with pytest.raises(PermissionError) as excinfo:
        tool.run("git push origin main")
    assert "不想要" in str(excinfo.value)
    assert shell.calls == []
    assert len(approval.requests) == 1


# ---- 静态 deny → PermissionError，审批回调与 shell 都不被调用 ----

def test_static_deny_raises_without_approval_or_execution():
    shell = RecordingShell()
    approval = StubApproval(approved=True)
    tool = ShellTool(policy=_policy(), approval=approval, shell_runner=shell)
    with pytest.raises(ShellPermissionDenied) as excinfo:
        tool.run("rm -rf /")
    assert excinfo.value.decision.rule_id == "static.catastrophic_delete"
    assert shell.calls == []
    assert approval.requests == []


# ---- allow → 直接执行，零回调 ----

def test_allow_runs_without_approval_callback():
    shell = RecordingShell(outputs={"npm install": "done"})
    approval = StubApproval(approved=True)
    tool = ShellTool(policy=_policy(), approval=approval, shell_runner=shell)
    assert tool.run("npm install") == "done"
    assert shell.calls == ["npm install"]
    assert approval.requests == []


# ---- TerminalApprovalCallback 最小桩 ----

def test_terminal_approval_callback_uses_config_io():
    io = ScriptedIO(lines=["y"])
    callback = TerminalApprovalCallback(io)
    result = callback(
        ApprovalRequest(
            command="git push origin main",
            segment="git push origin main",
            rule_id="whitelist.ask",
            reason="命中 ask 规则",
        )
    )
    assert result.approved is True
    assert any("git push origin main" in line for line in io.outputs)


def test_terminal_approval_callback_rejects_non_yes():
    io = ScriptedIO(lines=["n"])
    callback = TerminalApprovalCallback(io)
    result = callback(
        ApprovalRequest(
            command="git push origin main",
            segment="git push origin main",
            rule_id="whitelist.ask",
            reason="命中 ask 规则",
        )
    )
    assert result.approved is False
    assert result.note


# ---- AST 边界：ADR-0001 例外——审批在 REPL 宿主层，不进图 ----

FORBIDDEN_IMPORT_PREFIXES = (
    "langgraph",
    "project_agent.graph",
    "project_agent.nodes",
    "project_agent.protocol",
    "project_agent.repl",
)


@pytest.mark.parametrize(
    "module_name",
    ["shell_tool.py", "approval.py"],
)
def test_no_graph_layer_imports(module_name: str):
    tree = ast.parse((SRC_TOOLS / module_name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            for prefix in FORBIDDEN_IMPORT_PREFIXES:
                assert not name.startswith(prefix), (
                    f"{module_name} 不得 import {prefix}（ADR-0001：审批在 REPL 宿主层）"
                )
