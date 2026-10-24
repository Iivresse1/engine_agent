"""工具注册表钉板：角色面精确集、排除清单、TODO.md 写权独占、冻结映射。"""

from __future__ import annotations

import pytest

from project_agent.tools.decision import DecisionAction
from project_agent.tools.registry import (
    ALL_TOOLS,
    ASK_AGENT,
    ASK_AGENT_TOOLS,
    BUILDER,
    DEMO_AGENT,
    EXCLUDED_TOOLS,
    WAY1_ACTOR,
    ToolRegistry,
    UnknownRoleError,
)

ALL_ROLE_SET = frozenset({BUILDER, DEMO_AGENT, WAY1_ACTOR, ASK_AGENT})


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


def test_all_tools_is_exactly_15():
    assert len(ALL_TOOLS) == 15
    assert len(set(ALL_TOOLS)) == 15


def test_excluded_tools_is_exactly_14():
    assert len(EXCLUDED_TOOLS) == 14
    assert len(set(EXCLUDED_TOOLS)) == 14


def test_ask_agent_face_is_exact_10_tools():
    assert set(ASK_AGENT_TOOLS) == {
        "FileRead",
        "Glob",
        "Grep",
        "ReadProjectDocs",
        "NotepadRead",
        "NotepadAdd",
        "WebSearch",
        "WebFetch",
        "AskUserQuestion",
        "SkillRecommend",
    }
    assert len(ASK_AGENT_TOOLS) == 10


def test_ask_agent_face_has_no_write_or_shell_tools():
    face = set(registry_face := ToolRegistry().tools_for(ASK_AGENT))
    assert registry_face is not None
    for forbidden in ("FileWrite", "FileEdit", "Shell", "TodoWrite", "DocScaffold"):
        assert forbidden not in face


def test_three_full_roles_share_same_full_toolset(registry: ToolRegistry):
    faces = {registry.tools_for(role) for role in (BUILDER, DEMO_AGENT, WAY1_ACTOR)}
    assert len(faces) == 1
    assert faces.pop() == ALL_TOOLS


def test_excluded_tools_never_appear_in_any_face(registry: ToolRegistry):
    for role in ALL_ROLE_SET:
        face = set(registry.tools_for(role))
        for excluded in EXCLUDED_TOOLS:
            assert excluded not in face


def test_role_toolsets_mapping_is_frozen(registry: ToolRegistry):
    with pytest.raises(TypeError):
        registry.role_toolsets[ASK_AGENT] = ("Shell",)  # type: ignore[index]


def test_unknown_role_raises(registry: ToolRegistry):
    with pytest.raises(UnknownRoleError):
        registry.tools_for("root")
    with pytest.raises(UnknownRoleError):
        registry.check("nobody", "FileRead")


def test_check_allows_in_face_tool(registry: ToolRegistry):
    d = registry.check(ASK_AGENT, "FileRead")
    assert d.action is DecisionAction.ALLOW
    assert d.rule_id
    assert d.reason


def test_check_denies_face_violation(registry: ToolRegistry):
    d = registry.check(ASK_AGENT, "FileWrite")
    assert d.action is DecisionAction.DENY
    assert d.rule_id
    assert d.reason


def test_check_denies_excluded_tool(registry: ToolRegistry):
    d = registry.check(BUILDER, "AgentTool")
    assert d.action is DecisionAction.DENY


def test_todo_write_is_builder_exclusive(registry: ToolRegistry):
    # 面外角色先撞面 deny；此处专测"面内但非 Builder"的 TODO 写权独占规则
    for write_tool in ("FileWrite", "FileEdit", "DocScaffold"):
        denied = registry.check(WAY1_ACTOR, write_tool, target="docs/TODO.md")
        assert denied.action is DecisionAction.DENY
        assert denied.rule_id == "registry.todo_write"
    allowed = registry.check(BUILDER, "FileWrite", target="docs/TODO.md")
    assert allowed.action is DecisionAction.ALLOW
    face_denied = registry.check(ASK_AGENT, "FileWrite", target="docs/TODO.md")
    assert face_denied.rule_id == "registry.face"


def test_todo_write_basename_case_insensitive(registry: ToolRegistry):
    d = registry.check(ASK_AGENT, "FileEdit", target=r"D:\x\todo.MD")
    assert d.action is DecisionAction.DENY


def test_todo_read_is_unrestricted(registry: ToolRegistry):
    d = registry.check(ASK_AGENT, "FileRead", target="docs/TODO.md")
    assert d.action is DecisionAction.ALLOW


def test_non_todo_target_not_special_cased(registry: ToolRegistry):
    d = registry.check(ASK_AGENT, "FileRead", target="docs/README.md")
    assert d.action is DecisionAction.ALLOW
