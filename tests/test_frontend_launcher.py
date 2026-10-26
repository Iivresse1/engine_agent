"""前端产物发现/下载（UX-3 片 4）——纯逻辑，零网络、零图依赖。"""

from __future__ import annotations

import io
import pathlib
import tarfile
import zipfile

import pytest

from project_agent.frontend_launcher import (
    FrontendError,
    describe,
    ensure_frontend,
    entry_path,
    frontend_root,
    frontend_url,
    install_dir,
    is_available,
    resolve_available,
)


def _make_zip(entry: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("README.md", "产物说明")
        if entry:
            bundle.writestr("dist/main.js", "// entry")
    return buffer.getvalue()


def _make_tar_with_root() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, content in (("frontend/dist/main.js", "// entry"), ("frontend/README.md", "x")):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _write_entry(directory: pathlib.Path) -> pathlib.Path:
    target = entry_path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("// entry", encoding="utf-8")
    return target


def test_frontend_root_is_user_level():
    assert frontend_root() == pathlib.Path.home() / ".project-agent" / "frontend"


def test_install_dir_layout(tmp_path):
    assert install_dir("0.1.0", tmp_path) == tmp_path / "0.1.0"


def test_entry_path_is_dist_main_js(tmp_path):
    assert entry_path(tmp_path) == tmp_path / "dist" / "main.js"


def test_is_available_requires_entry_file(tmp_path):
    assert is_available(tmp_path) is False
    _write_entry(tmp_path)
    assert is_available(tmp_path) is True


def test_resolve_prefers_installed_over_dev(tmp_path, monkeypatch):
    """已安装目录优先于开发态候选。"""
    installed = install_dir("9.9.9", tmp_path)
    _write_entry(installed)
    monkeypatch.setattr(
        "project_agent.frontend_launcher.bundled_candidates", lambda: [tmp_path / "dev"]
    )
    found = resolve_available("9.9.9", tmp_path)
    assert found is not None
    assert found[0] == installed
    assert found[1] is False  # 已安装，不是开发态


def test_resolve_falls_back_to_dev_candidate(tmp_path, monkeypatch):
    dev = tmp_path / "dev"
    _write_entry(dev)
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [dev])
    found = resolve_available("1.2.3", tmp_path / "empty_root")
    assert found is not None
    assert found[0] == dev
    assert found[1] is True  # 开发态


def test_resolve_returns_none_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])
    assert resolve_available("0.0.0", tmp_path) is None


def test_frontend_url_from_arg_and_env(monkeypatch):
    monkeypatch.delenv("PROJECT_AGENT_FRONTEND_URL", raising=False)
    assert frontend_url("1.0.0") is None
    assert frontend_url("1.0.0", "https://x/y.zip") == "https://x/y.zip"
    monkeypatch.setenv("PROJECT_AGENT_FRONTEND_URL", "https://env/z.zip")
    assert frontend_url("1.0.0") == "https://env/z.zip"
    assert frontend_url("1.0.0", "https://arg/y.zip") == "https://arg/y.zip"


def test_ensure_returns_available_dev_without_download(tmp_path, monkeypatch):
    """产物已可用 → 不触发下载（fetch 不被调用）。"""
    dev = tmp_path / "dev"
    _write_entry(dev)
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [dev])
    called: list[str] = []
    result = ensure_frontend(
        "1.0.0",
        root=tmp_path / "root",
        fetch=lambda url: called.append(url) or b"",
    )
    assert result == dev
    assert called == []


def test_ensure_returns_none_when_no_url(tmp_path, monkeypatch):
    """未分发（无 URL）→ None，调用方退终端；不下载不报错。"""
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])
    monkeypatch.delenv("PROJECT_AGENT_FRONTEND_URL", raising=False)
    assert ensure_frontend("1.0.0", root=tmp_path) is None


def test_ensure_downloads_zip_and_installs(tmp_path, monkeypatch):
    """下载 zip → 解包 → 安装到 <root>/<version>/ → 入口可用。"""
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])
    result = ensure_frontend(
        "2.0.0",
        root=tmp_path,
        url="https://example/frontend.zip",
        fetch=lambda url: _make_zip(),
    )
    assert result is not None
    assert result == install_dir("2.0.0", tmp_path)
    assert is_available(result)
    assert not (tmp_path / "2.0.0.staging").exists(), "暂存目录须清理"


def test_ensure_downloads_tar_with_top_level_dir(tmp_path, monkeypatch):
    """压缩包带顶层目录的形态也要认（取唯一子目录）。"""
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])
    result = ensure_frontend(
        "2.1.0",
        root=tmp_path,
        url="https://example/frontend.tar.gz",
        fetch=lambda url: _make_tar_with_root(),
    )
    assert result is not None
    assert is_available(result)


def test_ensure_returns_none_on_download_failure(tmp_path, monkeypatch):
    """下载抛错 → None（降级优先于报错）。"""
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])

    def boom(url: str) -> bytes:
        raise OSError("网络不通")

    assert ensure_frontend("3.0.0", root=tmp_path, url="https://x/y", fetch=boom) is None


def test_ensure_returns_none_on_empty_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])
    assert ensure_frontend("3.0.0", root=tmp_path, url="https://x/y", fetch=lambda url: b"") is None


def test_ensure_returns_none_when_archive_lacks_entry(tmp_path, monkeypatch):
    """产物缺入口 → None，且不留半装状态。"""
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])
    result = ensure_frontend(
        "4.0.0",
        root=tmp_path,
        url="https://x/y",
        fetch=lambda url: _make_zip(entry=False),
    )
    assert result is None
    assert not install_dir("4.0.0", tmp_path).exists()
    assert not (tmp_path / "4.0.0.staging").exists()


def test_extract_rejects_path_traversal(tmp_path, monkeypatch):
    """防目录穿越：含 `../` 的产物包必须拒绝。"""
    monkeypatch.setattr("project_agent.frontend_launcher.bundled_candidates", lambda: [])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("../evil.txt", "x")
        bundle.writestr("dist/main.js", "// entry")
    result = ensure_frontend(
        "5.0.0", root=tmp_path, url="https://x/y", fetch=lambda url: buffer.getvalue()
    )
    assert result is None, "含穿越路径的产物必须被拒（整包失败，不留半装）"


def test_extract_rejects_absolute_path(tmp_path):
    from project_agent.frontend_launcher import _extract

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("/abs/evil.txt", "x")
    archive = tmp_path / "bundle.zip"
    archive.write_bytes(buffer.getvalue())
    with pytest.raises(FrontendError, match="非法路径"):
        _extract(archive, tmp_path / "out")


def test_extract_rejects_unknown_format(tmp_path):
    from project_agent.frontend_launcher import _extract

    archive = tmp_path / "bundle.bin"
    archive.write_bytes(b"not an archive")
    with pytest.raises(FrontendError, match="无法识别"):
        _extract(archive, tmp_path / "out")


def test_describe_reports_state(tmp_path):
    assert describe(None)["available"] is False
    _write_entry(tmp_path)
    described = describe(tmp_path)
    assert described["available"] is True
    assert described["entry"].endswith("main.js")


def test_launcher_has_no_graph_dependency():
    """红线：启动器不得依赖图/节点（与 transport/messages 同法）。"""
    import ast

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "project_agent" / "frontend_launcher.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {"project_agent.nodes", "project_agent.graph", "langgraph", "langchain_core"}
    assert imported & forbidden == set(), f"启动器不得依赖图: {sorted(imported & forbidden)}"


def test_launcher_does_not_import_network_lib_at_top_level():
    """Q39 红线同法：httpx 只能函数内惰性导入。"""
    import ast

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "project_agent" / "frontend_launcher.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    top: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top.add(node.module)
    assert "httpx" not in top, "顶层 import httpx 即倒退"
