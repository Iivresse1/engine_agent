"""工具层：注册表（权限矩阵）+ shell 判定管线（静态检查 → 白名单 → 两旋钮）。

模块布局（不动 nodes/graph/repl 主线）：
- decision.py       Decision 值对象（三态 + 跨段聚合）
- registry.py       ToolRegistry 构造期角色工具面
- knobs.py          Boundary × Interrupt 两旋钮（full/yolo 仅 flag 可达）
- static_checker.py 8 类形态学静态检查器（拆段/剥壳/解析失败 fail-closed）
- shell_policy.py   判定管线 + shell_policy.json 白名单
- approval.py       审批协议（ADR-0001 例外：REPL 宿主层同步回调）
- shell_tool.py     ShellTool 执行入口

不保证（调研 §10.3 的 5 条，各模块 docstring 内有同一份清单）：
1. 形态学检查会漏（find -delete、脚本内部逻辑、未枚举命令）；
2. 引号内字面量会误伤（fail-closed 方向）；
3. --force 误中递归 flag、PowerShell 反引号误中命令替换（fail-closed 方向）；
4. 语义级风险（外发内容/供应链/不可解析目标/口头边界/注入语料）留人工；
5. yolo+full 档无任何保护，OS 级沙箱是 v2+。
"""

from .decision import Decision, DecisionAction
from .registry import ToolRegistry, UnknownRoleError
from .knobs import Boundary, Interrupt, ShellKnobs, from_decision_mode
from .shell_policy import ShellPolicy, WhitelistRules, load_rules
from .approval import (
    ApprovalRequest,
    ApprovalResult,
    ShellApprovalCallback,
    TerminalApprovalCallback,
)
from .shell_tool import ShellPermissionDenied, ShellRunner, ShellTool

__all__ = [
    "ApprovalRequest",
    "ApprovalResult",
    "Boundary",
    "Decision",
    "DecisionAction",
    "Interrupt",
    "ShellApprovalCallback",
    "ShellKnobs",
    "ShellPermissionDenied",
    "ShellPolicy",
    "ShellRunner",
    "ShellTool",
    "TerminalApprovalCallback",
    "ToolRegistry",
    "UnknownRoleError",
    "WhitelistRules",
    "from_decision_mode",
    "load_rules",
]
