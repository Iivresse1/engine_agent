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
    """兜底扫描：整个主包**顶层**零网络上报 import（Q39：账单不外发云端）。

    豁免 gui_config.py（14 票）：测试连接是**用户主动**的入网动作
    （点按钮才发生），且 httpx 已改惰性导入（_httpx() 函数内）——
    与账单/审计的"自动外发"红线语义不同；红线对象仍是 ledger/audit。
    """
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        if py.name == "gui_config.py":
            continue  # 用户主动测试连接（惰性导入）；非上报路径
        tree = ast.parse(py.read_text(encoding="utf-8"))
        bad = _imported_top_levels(tree) & _NETWORK_MODULES
        if bad:
            offenders.append(f"{py.name}: {sorted(bad)}")
    assert not offenders, f"主包存在网络上报 import: {offenders}"


def test_gui_config_httpx_is_function_local_not_module_level():
    """gui_config 的 httpx 只能出现在函数体内（惰性）；模块顶层出现即倒退。"""
    tree = ast.parse((SRC / "gui_config.py").read_text(encoding="utf-8"))
    # 收集全部顶层节点（模块级）里引用 httpx 的名字
    module_level_names: set[str] = set()
    for node in tree.body:  # 只走顶层——函数体不在 tree.body 直接层
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == "httpx":
                module_level_names.add(sub.id)
            if isinstance(sub, ast.Attribute) and getattr(sub.value, "id", "") == "httpx":
                module_level_names.add("httpx")
    # 顶层只允许出现赋值目标 `httpx = _httpx()`（函数体内局部名）
    offenders = [
        node.lineno
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and any(alias.name.split(".")[0] == "httpx" for alias in getattr(node, "names", []))
    ]
    assert not offenders, f"gui_config 顶层 import httpx（行 {offenders}）——须走 _httpx() 惰性"


def test_ledger_modules_declare_local_only_contract():
    """账单/审计模块自述本地契约：模块 docstring 声明本地持久化（Q39）。"""
    for name in _LEDGER_MODULES:
        doc = ast.get_docstring(ast.parse((SRC / name).read_text(encoding="utf-8")))
        assert doc is not None, f"{name} 缺模块 docstring"
        assert "本地" in doc, f"{name} docstring 未声明本地契约"
