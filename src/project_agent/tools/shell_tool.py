"""ShellTool：policy 判决 → 审计（deny/ask）→ 审批回调（ask 时）→ shell runner 的执行入口。

ADR-0001 例外边界：审批在 REPL 宿主层同步完成（ShellApprovalCallback），
不进图、不落 turn_end_reason；静态 deny 不触发任何回调与副作用。
审计接线（03 判决 → 04 sink）：deny/ask 在判决时刻落 AuditLog（可选注入），
allow 不落账；无 audit 参数时行为与纯 03 票一致。

不保证（调研 §10.3）：本层信任 policy 的形态学判定（其不保证清单见
static_checker 模块 docstring）；审批回调的防超时/防注入属宿主职责。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from project_agent.audit import AuditEvent, AuditLog

from .approval import ApprovalRequest, ShellApprovalCallback
from .decision import Decision, DecisionAction
from .shell_policy import ShellPolicy


class ShellRunner(Protocol):
    """shell 执行器协议：RecordingShell（测试替身）与真实实现都满足。"""

    def run(self, command: str) -> str: ...


class ShellPermissionDenied(PermissionError):
    """静态/白名单/边界 deny：携带来源 Decision，含 rule_id 与 reason。"""

    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        super().__init__(
            f"shell 命令被拒绝（{decision.rule_id}）: {decision.reason}；"
            f"segment={decision.segment!r}"
        )


class ShellTool:
    """工具入口：run(command) -> 输出文本；deny 抛 ShellPermissionDenied。"""

    def __init__(
        self,
        policy: ShellPolicy,
        approval: ShellApprovalCallback,
        shell_runner: ShellRunner,
        *,
        audit: AuditLog | None = None,
        thread_id: str = "",
    ) -> None:
        self._policy = policy
        self._approval = approval
        self._runner = shell_runner
        self._audit = audit
        self._thread_id = thread_id

    def _record(self, decision: Decision) -> None:
        """deny/ask 判决落审计 sink（判决时刻，与审批结果无关）。"""
        if self._audit is None:
            return
        self._audit.append(
            AuditEvent(
                rule_id=decision.rule_id,
                command=decision.segment or decision.command,
                reason=decision.reason,
                thread_id=self._thread_id,
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def run(self, command: str) -> str:
        decision = self._policy.check(command)
        if decision.action is DecisionAction.DENY:
            self._record(decision)
            raise ShellPermissionDenied(decision)
        if decision.action is DecisionAction.ASK:
            self._record(decision)
            request = ApprovalRequest(
                command=decision.command,
                segment=decision.segment,
                rule_id=decision.rule_id,
                reason=decision.reason,
            )
            result = self._approval(request)
            if not result.approved:
                raise PermissionError(
                    f"用户拒绝执行: {command}"
                    + (f"（{result.note}）" if result.note else "")
                )
        return self._runner.run(command)


__all__ = ["ShellPermissionDenied", "ShellRunner", "ShellTool"]
