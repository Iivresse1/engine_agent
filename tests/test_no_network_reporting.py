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


# 惰性导入模块：网络库只允许出现在**函数体内**（用户主动入网动作，非上报路径）。
#   gui_config.py        —— 14 票「测试连接」按钮（用户点才发生）
#   frontend_launcher.py —— UX-3 片 4「前端产物首次运行下载」（用户启用前端才发生）
_LAZY_NETWORK_MODULES = frozenset({"gui_config.py", "frontend_launcher.py"})


def _imported_top_levels(tree: ast.AST) -> set[str]:
    """AST 收集**模块顶层**的 import 模块名（函数体内惰性导入不计）。

    语义钉板：Q39 红线是"不自动上报 + 顶层不 import 网络库"——顶层 import
    意味着进程一启动就具备外发能力；函数内惰性导入则只在用户主动动作时发生。
    """
    tops: set[str] = set()
    for node in tree.body:  # 只走模块顶层，不下潜函数/类体
        if isinstance(node, ast.Import):
            tops.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
    return tops


def test_ledger_and_audit_modules_import_no_network_libs():
    """账单/审计模块 import 集不含任何网络上报库（含 LangSmith）。

    这两个模块连函数内也不许有（它们是上报路径的载体本身）。
    """
    for name in _LEDGER_MODULES:
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
        anywhere: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                anywhere.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                anywhere.add(node.module.split(".")[0])
        offenders = anywhere & _NETWORK_MODULES
        assert not offenders, f"{name} 引入网络上报库: {sorted(offenders)}"


def test_whole_package_imports_no_network_libs():
    """兜底扫描：整个主包**顶层**零网络上报 import（Q39：账单不外发云端）。

    顶层 import = 进程一启动就有外发能力 → 禁止。函数内惰性导入不算
    （用户主动动作：测试连接 / 前端产物下载）。
    """
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        bad = _imported_top_levels(tree) & _NETWORK_MODULES
        if bad:
            offenders.append(f"{py.name}: {sorted(bad)}")
    assert not offenders, f"主包顶层存在网络上报 import: {offenders}"


def test_lazy_network_modules_do_not_import_at_top_level():
    """惰性模块：网络库只能出现在函数体内（顶层出现即倒退）。"""
    for name in _LAZY_NETWORK_MODULES:
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
        bad = _imported_top_levels(tree) & _NETWORK_MODULES
        assert not bad, f"{name} 顶层 import 网络库: {sorted(bad)}——须函数内惰性导入"


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
