"""Q39 红线：账单/审计无任何网络上报路径（结构性断言，票验收第 4 条）。

钉板来源：decisions.md Q39——本地账单，LangSmith 明确不引入（用户：会干扰主线设计）；
spec『可观测』节与 Out of Scope（LangSmith / 云端观测——已钉不引入）。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "project_agent"

# 账单与审计模块——本票红线对象
_LEDGER_MODULES = ("ledger.py", "audit.py")

# 网络上报库黑名单（顶层模块名）
_NETWORK_MODULES = frozenset(
    {"httpx", "httpcore", "requests", "urllib3", "aiohttp", "socket", "langsmith", "opentelemetry"}
)


def _imported_top_levels(tree: ast.AST) -> set[str]:
    """AST 收集 import 顶层模块名（import x.y → x；from x import y → x）。"""
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
    return tops


def test_ledger_and_audit_modules_import_no_network_libs():
    """账单/审计模块 import 集不含任何网络上报库（含 LangSmith）。"""
    for name in _LEDGER_MODULES:
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
        offenders = _imported_top_levels(tree) & _NETWORK_MODULES
        assert not offenders, f"{name} 引入网络上报库: {sorted(offenders)}"


def test_whole_package_imports_no_network_libs():
    """兜底扫描：整个主包零网络上报 import（Q39：账单不外发云端）。"""
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        bad = _imported_top_levels(tree) & _NETWORK_MODULES
        if bad:
            offenders.append(f"{py.name}: {sorted(bad)}")
    assert not offenders, f"主包存在网络上报 import: {offenders}"


def test_ledger_modules_declare_local_only_contract():
    """账单/审计模块自述本地契约：模块 docstring 声明本地持久化（Q39）。"""
    for name in _LEDGER_MODULES:
        doc = ast.get_docstring(ast.parse((SRC / name).read_text(encoding="utf-8")))
        assert doc is not None, f"{name} 缺模块 docstring"
        assert "本地" in doc, f"{name} docstring 未声明本地契约"
