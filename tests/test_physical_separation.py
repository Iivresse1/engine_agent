"""测试与主项目物理分隔（spec v1.1 Testing Decisions 钉板五条）。"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "project_agent"
TESTS = ROOT / "tests"


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_src_layout_declared():
    assert SRC.is_dir()
    data = _pyproject()
    assert data["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


def test_runtime_deps_exclude_test_tools():
    data = _pyproject()
    runtime = data["project"]["dependencies"]
    assert not any("pytest" in d or "ruff" in d for d in runtime)
    test_extras = data["project"]["optional-dependencies"]["test"]
    assert any("pytest" in d for d in test_extras)


def test_main_package_never_imports_tests():
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in {"tests", "conftest"}:
                    offenders.append(f"{py.name}: {name}")
    assert not offenders, f"主包反向依赖测试树: {offenders}"


def test_doubles_live_outside_main_package():
    for name in ("fake_model", "fake_shell", "scripted_io"):
        assert (TESTS / "doubles" / f"{name}.py").exists()
        assert not (SRC / f"{name}.py").exists()
    assert not (SRC / "doubles").exists()


def test_test_config_separate_from_runtime_config():
    data = _pyproject()
    ini = data["tool"]["pytest"]["ini_options"]
    assert ini["testpaths"] == ["tests"]
    assert "markers" in ini
    # 运行时配置（模型/API key 的 config.json）绝不进打包元数据
    assert "api_key" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
