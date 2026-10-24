"""白名单包数据打进 wheel：project_agent.tools 的 *.json 随包分发。"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_tools_json_is_package_data():
    data = _pyproject()
    pkg_data = data["tool"]["setuptools"]["package-data"]
    assert pkg_data.get("project_agent.tools") == ["*.json"]


def test_shell_policy_json_ships_with_package():
    assert (ROOT / "src" / "project_agent" / "tools" / "shell_policy.json").exists()
