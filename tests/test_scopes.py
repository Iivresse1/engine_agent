"""09 票 A 段：scopes 规则文件——作用域规则 + 工具子集交集语义。

接缝：scopes 模块公开 API（RULES / rule_for / ALLOWED_TOOLS_BY_SCOPE /
tools_for_scope）。工具子集终裁语义 = scope 声明集 ∩ 静态矩阵（registry_full）。
"""

from __future__ import annotations

from project_agent.scopes import (
    ALLOWED_TOOLS_BY_SCOPE,
    RULES,
    rule_for,
    tools_for_scope,
)
from project_agent.tools.registry import ALL_TOOLS

FULL = frozenset(ALL_TOOLS)


def test_rules_cover_main_src_docs():
    """规则文件三作用域文案（票面字面）。"""
    assert RULES["main"] == "当前为主工作区：优先推进待办；工具面向构建与文件读写。"
    assert RULES["src"] == "当前在源码区：只关注代码文件的组织与实现细节。"
    assert RULES["docs"] == "当前在文档区：只关注文档的结构与内容撰写。"


def test_rule_for_unknown_scope_falls_back_to_main():
    """未知 scope → RULES["main"]（默认回退）。"""
    assert rule_for("main") == RULES["main"]
    assert rule_for("src") == RULES["src"]
    assert rule_for("docs") == RULES["docs"]
    assert rule_for("nope") == RULES["main"]
    assert rule_for("") == RULES["main"]


def test_main_scope_declares_full_registry_toolset():
    """main 声明集 = registry 全 15 件（导入 registry 模块常量拼）。"""
    assert ALLOWED_TOOLS_BY_SCOPE["main"] == FULL
    assert len(FULL) == 15
    assert tools_for_scope("main", FULL) == FULL


def test_src_scope_subset_is_six_tools():
    """src = FileRead/Glob/Grep/FileWrite/FileEdit/Shell（六件）。"""
    expected = frozenset({"FileRead", "Glob", "Grep", "FileWrite", "FileEdit", "Shell"})
    assert ALLOWED_TOOLS_BY_SCOPE["src"] == expected
    assert tools_for_scope("src", FULL) == expected


def test_docs_scope_subset_excludes_shell():
    """docs 五件：无 Shell。"""
    expected = frozenset({"FileRead", "Glob", "Grep", "FileWrite", "FileEdit"})
    assert tools_for_scope("docs", FULL) == expected


def test_tools_for_scope_intersects_with_static_matrix():
    """终裁语义：scope 声明集 ∩ registry_full——静态矩阵更小时只剩交集。"""
    smaller = frozenset({"FileRead", "Glob", "Shell"})
    assert tools_for_scope("src", smaller) == frozenset({"FileRead", "Glob", "Shell"})
    docs_small = frozenset({"FileRead", "FileWrite", "Shell"})
    assert tools_for_scope("docs", docs_small) == frozenset({"FileRead", "FileWrite"})


def test_tools_for_scope_out_of_bounds_tool_dropped():
    """验收 3 越界：规则声明 NotATool（不在静态矩阵内）→ 交集后不生效。"""
    ALLOWED_TOOLS_BY_SCOPE["broken"] = frozenset({"FileRead", "NotATool"})
    try:
        subset = tools_for_scope("broken", FULL)
    finally:
        del ALLOWED_TOOLS_BY_SCOPE["broken"]
    assert "NotATool" not in subset
    assert subset == frozenset({"FileRead"})


def test_tools_for_scope_unknown_scope_uses_main_intersection():
    """未知 scope → main 声明集的交集（回退后同样受矩阵约束）。"""
    restricted = frozenset({"FileRead", "Glob"})
    assert tools_for_scope("whatever", restricted) == frozenset({"FileRead", "Glob"})
    # main 声明集不含的工具即便进了矩阵也不生效（交集语义）
    partial = frozenset({"FileRead", "NotATool"})
    assert tools_for_scope("unknown-scope", partial) == frozenset({"FileRead"})
