"""工具注册表：构造期预注册的角色工具面（权限矩阵的代码层强制）。

矩阵钉板（票 03 + spec『工具权限』节）：
- 全工具 15 件 = FileRead/Glob/Grep/ReadProjectDocs/NotepadRead/NotepadAdd/
  FileWrite/FileEdit/TodoWrite/WebSearch/WebFetch/Shell/AskUserQuestion/
  DocScaffold/SkillRecommend
- Builder / DemoAgent / way1 Actor = 全工具（DemoAgent 全工具是 2026-10-24 v2 修订，
  旧矩阵行作废——ADR-0003：demo 运行权在用户，不靠裁工具面实现）
- AskAgent = 只读 4 件 + NotepadRead/NotepadAdd + WebSearch/WebFetch +
  AskUserQuestion + SkillRecommend（共 10 件；NotepadRead 由 spec v1.1+Q49 钉，
  票面"只读四件"是缩写）
- 排除 14 件钉死：AgentTool/SkillTool/EnterPlanMode/ExitPlanMode/TaskCreate/TaskRead/
  TaskUpdate/TaskDelete/TaskList/TaskRun/SendMessage/NotebookEdit/MCPTool/LSPTool
- 交付物 TODO.md 写权 Builder 独占（check 的 target 参数按 basename 大小写不敏感
  比对；FileRead 读 TODO.md 不受限）

不保证（调研 §10.3）：本模块只做面裁剪，不判定工具参数内容；shell 命令内容由
静态正则检查器与两旋钮负责，其各自的"不保证"清单见对应模块 docstring。
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .decision import Decision, DecisionAction

# ---- 角色常量 ----
BUILDER = "builder"
DEMO_AGENT = "demo_agent"
WAY1_ACTOR = "way1_actor"
ASK_AGENT = "ask_agent"

# ---- 工具名常量（全 15 件 + 排除件钉板）----
FILE_READ = "FileRead"
GLOB = "Glob"
GREP = "Grep"
READ_PROJECT_DOCS = "ReadProjectDocs"
NOTEPAD_READ = "NotepadRead"
NOTEPAD_ADD = "NotepadAdd"
FILE_WRITE = "FileWrite"
FILE_EDIT = "FileEdit"
TODO_WRITE = "TodoWrite"
WEB_SEARCH = "WebSearch"
WEB_FETCH = "WebFetch"
SHELL = "Shell"
ASK_USER_QUESTION = "AskUserQuestion"
DOC_SCAFFOLD = "DocScaffold"
SKILL_RECOMMEND = "SkillRecommend"

ALL_TOOLS: tuple[str, ...] = (
    FILE_READ,
    GLOB,
    GREP,
    READ_PROJECT_DOCS,
    NOTEPAD_READ,
    NOTEPAD_ADD,
    FILE_WRITE,
    FILE_EDIT,
    TODO_WRITE,
    WEB_SEARCH,
    WEB_FETCH,
    SHELL,
    ASK_USER_QUESTION,
    DOC_SCAFFOLD,
    SKILL_RECOMMEND,
)

EXCLUDED_TOOLS: tuple[str, ...] = (
    "AgentTool",
    "SkillTool",
    "EnterPlanMode",
    "ExitPlanMode",
    "TaskCreate",
    "TaskRead",
    "TaskUpdate",
    "TaskDelete",
    "TaskList",
    "TaskRun",
    "SendMessage",
    "NotebookEdit",
    "MCPTool",
    "LSPTool",
)

ASK_AGENT_TOOLS: tuple[str, ...] = (
    FILE_READ,
    GLOB,
    GREP,
    READ_PROJECT_DOCS,
    NOTEPAD_READ,
    NOTEPAD_ADD,
    WEB_SEARCH,
    WEB_FETCH,
    ASK_USER_QUESTION,
    SKILL_RECOMMEND,
)

_ROLE_TOOLSETS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        BUILDER: ALL_TOOLS,
        DEMO_AGENT: ALL_TOOLS,
        WAY1_ACTOR: ALL_TOOLS,
        ASK_AGENT: ASK_AGENT_TOOLS,
    }
)

# 交付物 TODO.md 写权 Builder 独占（读不受限）
_DELIVERABLE_TODO = "todo.md"
_TODO_WRITE_ROLES: frozenset[str] = frozenset({BUILDER})


class UnknownRoleError(ValueError):
    """未知角色：权限矩阵在构造期钉死，角色不在矩阵内即结构性错误。"""


class ToolRegistry:
    """构造期工具面注册表：LLM 不可越权（面外工具根本不存在，无从调用）。"""

    @property
    def role_toolsets(self) -> Mapping[str, tuple[str, ...]]:
        """冻结的角色→工具面映射（MappingProxyType，赋值抛 TypeError）。"""
        return _ROLE_TOOLSETS

    def tools_for(self, role: str) -> tuple[str, ...]:
        """返回该角色的工具面（构造期固定）。未知角色抛 UnknownRoleError。"""
        try:
            return _ROLE_TOOLSETS[role]
        except KeyError as exc:
            raise UnknownRoleError(f"未知角色: {role!r}") from exc

    def check(self, role: str, tool: str, target: str | None = None) -> Decision:
        """判定角色能否用某工具（可选 target 交付物路径做细粒度判定）。

        - 工具在角色面内且非 Shell → allow
        - 工具在角色面内且为 Shell → allow（命令内容由 ShellPolicy 单独裁决，
          本层只管"有没有这个工具"）
        - target 为交付物 TODO.md 且工具为写类（FileWrite/FileEdit/DocScaffold）：
          仅 Builder 放行，其余角色 deny
        - 工具不在面内（含排除件、未知工具名）→ deny
        """
        toolset = self.tools_for(role)
        if tool not in toolset:
            return Decision(
                action=DecisionAction.DENY,
                rule_id="registry.face",
                reason=f"工具 {tool} 不在角色 {role} 的构造期工具面内",
                command=tool,
                segment=tool,
            )
        if target is not None and self._is_todo_write(tool, target):
            if role not in _TODO_WRITE_ROLES:
                return Decision(
                    action=DecisionAction.DENY,
                    rule_id="registry.todo_write",
                    reason="交付物 TODO.md 写权 Builder 独占",
                    command=tool,
                    segment=target,
                )
            return Decision(
                action=DecisionAction.ALLOW,
                rule_id="registry.todo_write",
                reason="Builder 独占交付物 TODO.md 写权",
                command=tool,
                segment=target,
            )
        return Decision(
            action=DecisionAction.ALLOW,
            rule_id="registry.face",
            reason=f"工具 {tool} 在角色 {role} 的构造期工具面内",
            command=tool,
            segment=tool,
        )

    @staticmethod
    def _is_todo_write(tool: str, target: str) -> bool:
        """写类工具 + 目标 basename 为 TODO.md（大小写不敏感）。"""
        if tool not in {FILE_WRITE, FILE_EDIT, DOC_SCAFFOLD}:
            return False
        name = target.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
        return name == _DELIVERABLE_TODO


__all__ = [
    "ALL_TOOLS",
    "ASK_AGENT",
    "ASK_AGENT_TOOLS",
    "BUILDER",
    "DEMO_AGENT",
    "EXCLUDED_TOOLS",
    "WAY1_ACTOR",
    "ToolRegistry",
    "UnknownRoleError",
]
