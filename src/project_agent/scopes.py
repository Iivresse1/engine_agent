"""作用域规则文件（09 票 A 段，Q51）：规则文案 + 工具声明集 + 交集裁剪。

作用域（GLOSSARY）：当前工作区域的声明——决定加载哪份规则文件、裁剪哪套
工具子集。工具子集终裁语义 = 规则声明集 ∩ 静态权限矩阵（registry_full，
构造期预注册全集）——越界声明（不在矩阵内的工具名）交集后不生效。

main 的声明集从 tools.registry 模块常量拼（全 15 件，与静态矩阵一致）；
未知 scope 双重回退：规则文案→RULES["main"]，工具集→main 声明集的交集。
"""

from __future__ import annotations

from project_agent.tools.registry import ALL_TOOLS

RULES: dict[str, str] = {
    "main": "当前为主工作区：优先推进待办；工具面向构建与文件读写。",
    "src": "当前在源码区：只关注代码文件的组织与实现细节。",
    "docs": "当前在文档区：只关注文档的结构与内容撰写。",
}


def rule_for(scope: str) -> str:
    """作用域规则行文案；未知 scope → RULES["main"]（默认回退）。"""
    return RULES.get(scope, RULES["main"])


ALLOWED_TOOLS_BY_SCOPE: dict[str, frozenset[str]] = {
    # main = 全 15 件（导入 registry 模块常量拼，与静态矩阵一致）
    "main": frozenset(ALL_TOOLS),
    "src": frozenset({"FileRead", "Glob", "Grep", "FileWrite", "FileEdit", "Shell"}),
    "docs": frozenset({"FileRead", "Glob", "Grep", "FileWrite", "FileEdit"}),
}


def tools_for_scope(scope: str, registry_full: frozenset[str]) -> frozenset[str]:
    """工具子集 = 规则声明集 ∩ 静态矩阵（终裁语义）。

    未知 scope → main 声明集的交集；声明集中不在矩阵内的工具（越界）
    交集后不生效——静态权限矩阵是硬上界。
    """
    declared = ALLOWED_TOOLS_BY_SCOPE.get(scope, ALLOWED_TOOLS_BY_SCOPE["main"])
    return declared & frozenset(registry_full)
