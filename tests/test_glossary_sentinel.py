r"""术语哨兵：GLOSSARY _Avoid_ 单词在 src 标识符面的机械强制。

分工边界：字符串键（state 契约面）归 test_dashboard_fields_cover_spec_contract
与断点协议表测试；标识符面（类/函数/变量/模块名）归本哨兵。

刻意不机械禁的判例（改动须过 review，且改这里先读 GLOSSARY 对应词条）：
- agent——产品名 project_agent 与角色名 DemoAgent 是裁定术语；泛称禁令只管
  给新的执行者节点起名，是判断题。
- memory——memory_store（final_report 长期记忆库）是裁定模块名；Notepad 词条
  的 memory 禁令指概念误用，判断题。
- 多词避免词（permission mode / shared state / todo list）——拆词后零散命中
  mode/state/todo 等钉定键，无法机械禁。
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "project_agent"

# GLOSSARY.md 各 _Avoid_ 行中可机械检查的单词 ASCII 子集
AVOID_TOKENS = frozenset(
    {"turn", "interrupt", "tag", "tier", "pipeline", "worker", "cache", "flag"}
)

# tools/ 子树是 shell 权限域：interrupt（两旋钮之一）与 flag（CLI 形态学）
# 在该域是 Q23 裁定术语，不是断点/gate 变量的概念误用。
PATH_TOKEN_EXEMPTS: dict[str, frozenset[str]] = {
    "tools": frozenset({"interrupt", "flag"}),
}

# 镜像 spec 钉死 state 键的标识符：键名契约归 spec 状态契约表，不归本哨兵
IDENTIFIER_EXEMPTS = frozenset({"turn_end_reason", "turn_end_payload"})


def _parts(name: str) -> set[str]:
    """CamelCase 与 snake_case 一次拆完：TurnEndReason/_run_turn → 词集。"""
    return {p.lower() for p in re.findall(r"[A-Za-z]+", name)}


def _identifiers(tree: ast.AST) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.lineno, node.name
        elif isinstance(node, ast.arg):
            yield node.lineno, node.arg
        elif isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, ast.alias):
            yield node.lineno, node.asname or node.name
        elif isinstance(node, ast.ExceptHandler) and node.name:
            yield node.lineno, node.name


def _violations() -> list[str]:
    out: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(SRC_ROOT)
        exempt: frozenset[str] = frozenset()
        for part in rel.parts:
            exempt |= PATH_TOKEN_EXEMPTS.get(part, frozenset())
        stem_hits = (_parts(rel.stem) & AVOID_TOKENS) - exempt
        if stem_hits:
            out.append(f"{rel}: 模块名命中 {sorted(stem_hits)}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, name in _identifiers(tree):
            if name in IDENTIFIER_EXEMPTS:
                continue
            hits = (_parts(name) & AVOID_TOKENS) - exempt
            if hits:
                out.append(f"{rel}:{lineno}: 标识符 '{name}' 命中 {sorted(hits)}")
    return out


def test_glossary_avoid_terms_absent_from_identifiers():
    violations = _violations()
    assert not violations, "\n".join(
        [
            "GLOSSARY _Avoid_ 术语混入标识符（轮次=round、断点=breakpoint……）：",
            *violations,
            "机械违规就地改名；确属裁定术语走 PATH_TOKEN_EXEMPTS/"
            "IDENTIFIER_EXEMPTS 钉定并写理由。",
        ]
    )
