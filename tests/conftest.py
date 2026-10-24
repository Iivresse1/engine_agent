"""pytest 公共夹具：tmp 工作区（config 隔离）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class Workspace:
    """隔离的工作区：独立的根目录与配置文件路径。"""

    root: Path
    config_path: Path


@pytest.fixture
def make_workspace(tmp_path: Path):
    """工作区工厂——测试内可创建多个互不干扰的工作区。"""

    def _make(name: str = "ws") -> Workspace:
        root = tmp_path / name
        return Workspace(root=root, config_path=root / "config" / "config.json")

    return _make


@pytest.fixture
def workspace(make_workspace) -> Workspace:
    return make_workspace()
