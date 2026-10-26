"""前端产物发现与首次运行下载（spec v2.2 Q71 裁②：「前端产物首次运行下载」）。

裁定要点：
- Python wheel **不打包**前端产物（保持纯 Python 体积）。
- 首次运行查找本地产物；没有则从发布地址下载到
  `~/.project-agent/frontend/<version>/` 并校验。
- **下载失败或用户拒绝 → 返回 None，调用方退终端降级渲染**（不阻塞使用）。

本模块是纯逻辑层（路径解析 / 可用性判定 / 下载与解包契约），网络行为经
`fetch` 注入，测试零网络。
"""

from __future__ import annotations

import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Callable

# 前端入口相对路径（与 frontend/package.json 的 bin 一致）
_ENTRY_RELATIVE = Path("dist") / "main.js"
# 发布地址环境变量（未发布时可显式指定；不硬编码不存在的 URL）
_URL_ENV = "PROJECT_AGENT_FRONTEND_URL"


class FrontendError(Exception):
    """前端产物安装失败（下载/解包/校验）。"""


def frontend_root() -> Path:
    """前端产物的用户级安装根：`~/.project-agent/frontend/`。"""
    return Path.home() / ".project-agent" / "frontend"


def install_dir(version: str, root: Path | None = None) -> Path:
    """某版本的安装目录：`<root>/<version>/`。"""
    base = frontend_root() if root is None else Path(root)
    return base / version


def entry_path(directory: Path) -> Path:
    """前端入口文件（`<dir>/dist/main.js`）。"""
    return Path(directory) / _ENTRY_RELATIVE


def is_available(directory: Path) -> bool:
    """产物可用 = 入口文件存在（其余资源缺失由前端启动时报错，不算"未安装"）。"""
    return entry_path(directory).is_file()


def bundled_candidates() -> list[Path]:
    """开发态候选：仓库内 `frontend/`（源码旁）与已构建的 `frontend/dist`。"""
    here = Path(__file__).resolve()
    # src/project_agent/frontend_launcher.py → 仓库根
    repo_root = here.parents[2]
    return [repo_root / "frontend"]


def resolve_available(version: str, root: Path | None = None) -> tuple[Path, bool] | None:
    """找可用产物：先已安装目录，再开发态候选。

    返回 `(目录, 是否为开发态)`；都没有返回 None。
    """
    installed = install_dir(version, root)
    if is_available(installed):
        return installed, False
    for candidate in bundled_candidates():
        if is_available(candidate):
            return candidate, True
    return None


def _extract(archive: Path, target: Path) -> None:
    """解包 zip/tar 到 target（防目录穿越：拒绝绝对路径与 `..`）。"""
    target.mkdir(parents=True, exist_ok=True)

    def _safe(name: str) -> Path:
        # 跨平台判定：Windows 上 Path("/abs/x") 并非 is_absolute，故显式查前缀。
        normalized = name.replace("\\", "/")
        if normalized.startswith("/") or normalized.startswith("//"):
            raise FrontendError(f"产物包含非法路径: {name}")
        first = normalized.split("/", 1)[0]
        if ":" in first:  # 盘符（C:/...）
            raise FrontendError(f"产物包含非法路径: {name}")
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if ".." in parts:
            raise FrontendError(f"产物包含非法路径: {name}")
        return target.joinpath(*parts) if parts else target

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                destination = _safe(member)
                if member.endswith("/"):
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, destination.open("wb") as sink:
                        shutil.copyfileobj(source, sink)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                destination = _safe(member.name)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as source:
                        if source is None:
                            continue
                        with destination.open("wb") as sink:
                            shutil.copyfileobj(source, sink)
        return
    raise FrontendError(f"无法识别的产物格式: {archive.name}")


def default_fetch(url: str, timeout: float = 60.0) -> bytes:
    """默认下载器（惰性导入 httpx——顶层不引网络库，Q39 红线同法）。"""
    import httpx

    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.content


def frontend_url(version: str, url: str | None = None) -> str | None:
    """产物的下载地址：显式参数优先，其次环境变量；都没有 → None（未分发）。"""
    if url:
        return url
    return str(os.environ.get(_URL_ENV) or "") or None


def ensure_frontend(
    version: str,
    *,
    root: Path | None = None,
    url: str | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> Path | None:
    """确保前端产物可用；返回目录，不可用返回 None（调用方退终端）。

    顺序：已安装 → 开发态 → 下载。下载失败一律返回 None（**不抛给调用方**，
    降级优先于报错）。
    """
    found = resolve_available(version, root)
    if found is not None:
        return found[0]

    target_url = frontend_url(version, url)
    if target_url is None:
        return None  # 未分发：调用方退终端

    downloader = fetch if fetch is not None else default_fetch
    try:
        payload = downloader(target_url)
    except Exception:  # noqa: BLE001 - 任何下载失败都退降级
        return None
    if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
        return None

    destination = install_dir(version, root)
    staging = destination.with_suffix(".staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    archive = staging / "frontend.bundle"
    archive.write_bytes(bytes(payload))
    try:
        extract_dir = staging / "unpacked"
        _extract(archive, extract_dir)
    except FrontendError:
        shutil.rmtree(staging, ignore_errors=True)
        return None

    # 压缩包可能带顶层目录，也可能直接就是产物根——两种形态都认
    source = extract_dir
    if not is_available(source):
        nested = [child for child in extract_dir.iterdir() if child.is_dir()]
        if len(nested) == 1 and is_available(nested[0]):
            source = nested[0]
    if not is_available(source):
        shutil.rmtree(staging, ignore_errors=True)
        return None

    shutil.rmtree(destination, ignore_errors=True)
    shutil.move(str(source), str(destination))
    shutil.rmtree(staging, ignore_errors=True)
    return destination if is_available(destination) else None


def describe(directory: Path | None) -> dict[str, Any]:
    """状态描述（供 `/status` 与冒烟脚本用）。"""
    if directory is None:
        return {"available": False, "entry": ""}
    return {"available": is_available(directory), "entry": str(entry_path(directory))}
