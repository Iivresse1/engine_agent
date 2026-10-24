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


# ---- 审计接线（03 checker 判决 → 04 AuditLog sink）：deny/ask 落审计，allow 不落 ----

def test_deny_records_audit_event(tmp_path):
    from project_agent.audit import AuditLog

    audit = AuditLog(tmp_path / "audit.jsonl")
    shell = RecordingShell()
    tool = ShellTool(
        policy=_policy(),
        approval=StubApproval(approved=True),
        shell_runner=shell,
        audit=audit,
        thread_id="t-audit",
    )
    with pytest.raises(ShellPermissionDenied):
        tool.run("rm -rf /")
    events = audit.events_for(thread_id="t-audit")
    assert len(events) == 1
    assert events[0].rule_id == "static.catastrophic_delete"
    assert events[0].command == "rm -rf /"
    assert events[0].reason
    assert shell.calls == []
    # 持久化：重载同一文件可见（04 票 AuditLog 语义）
    assert len(AuditLog(tmp_path / "audit.jsonl").events_for(thread_id="t-audit")) == 1


def test_ask_records_audit_event_at_decision_time(tmp_path):
    from project_agent.audit import AuditLog

    audit = AuditLog(tmp_path / "audit.jsonl")
    shell = RecordingShell(outputs={"git clone https://github.com/u/r.git": "cloned"})
    tool = ShellTool(
        policy=_policy(),
        approval=StubApproval(approved=True),
        shell_runner=shell,
        audit=audit,
        thread_id="t-audit",
    )
    tool.run("git clone https://github.com/u/r.git")
    events = audit.events_for(thread_id="t-audit")
    assert len(events) == 1
    assert events[0].rule_id == "whitelist.ask"
    assert events[0].command == "git clone https://github.com/u/r.git"


def test_allow_records_no_audit_event(tmp_path):
    from project_agent.audit import AuditLog

    audit = AuditLog(tmp_path / "audit.jsonl")
    tool = ShellTool(
        policy=_policy(),
        approval=StubApproval(approved=True),
        shell_runner=RecordingShell(),
        audit=audit,
        thread_id="t-audit",
    )
    tool.run("ls -la")
    assert audit.events_for(thread_id="t-audit") == []


def test_audit_is_optional_backwards_compatible():
    # 无 audit 参数时行为与 03 票交付完全一致（默认不接线）
    shell = RecordingShell(outputs={"ls -la": "ok"})
    tool = ShellTool(policy=_policy(), approval=StubApproval(approved=True), shell_runner=shell)
    assert tool.run("ls -la") == "ok"


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
