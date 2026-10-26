"""传输层（UX-2 第二片，spec v2.2『传输层』）——握手文件 + 上行分发 + 红线哨兵。

三裁（Q71）的代码化断言：
- 随机端口 + 握手文件（六字段往返、原子写、陈废识别）
- 断线复用 thread_id（握手文件必须携带）
- 只做收发，零业务逻辑（AST 哨兵）
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import pathlib

import pytest

from project_agent.transport import (
    HANDSHAKE_FILENAME,
    PROTOCOL_VERSION,
    HandshakeError,
    ProtocolServer,
    clear_handshake,
    handshake_path,
    is_quit,
    is_stale,
    new_handshake,
    read_handshake,
    write_handshake,
)


def run(coro):
    """在同步测试里跑一个协程（不引入 pytest-asyncio 依赖）。"""
    return asyncio.run(coro)


class StubDriver:
    """最小 SessionDriver 桩：记录收到的文本，返回预置下行消息。"""

    def __init__(self, reply: list[dict] | None = None) -> None:
        self.received: list[str] = []
        self._reply = reply if reply is not None else [{"type": "notice", "text": "ok"}]

    def handle_input(self, text: str) -> list[dict]:
        self.received.append(text)
        return self._reply


def test_handshake_filename_is_stable():
    assert HANDSHAKE_FILENAME == "handshake.json"


def test_handshake_path_sits_beside_state_db(tmp_path):
    state = tmp_path / "proj" / "state.db"
    assert handshake_path(state) == tmp_path / "proj" / "handshake.json"


def test_new_handshake_carries_pid_port_thread_and_version():
    handshake = new_handshake(51234, "t-abc")
    assert handshake.pid == os.getpid()
    assert handshake.port == 51234
    assert handshake.thread_id == "t-abc"
    assert handshake.protocol_version == PROTOCOL_VERSION
    assert handshake.started_at  # 非空时间串


def test_handshake_roundtrip(tmp_path):
    """写 → 读往返：六字段逐字保真（前端据此连接）。"""
    path = tmp_path / HANDSHAKE_FILENAME
    original = new_handshake(40000, "thread-1", pid=12345)
    write_handshake(path, original)
    assert read_handshake(path) == original


def test_handshake_write_is_atomic_leaves_no_tmp(tmp_path):
    path = tmp_path / HANDSHAKE_FILENAME
    write_handshake(path, new_handshake(40000, "t"))
    assert [p.name for p in tmp_path.iterdir()] == [HANDSHAKE_FILENAME]


def test_handshake_write_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "dir" / HANDSHAKE_FILENAME
    write_handshake(path, new_handshake(40000, "t"))
    assert path.exists()


def test_read_handshake_missing_raises(tmp_path):
    with pytest.raises(HandshakeError, match="不存在"):
        read_handshake(tmp_path / HANDSHAKE_FILENAME)


def test_read_handshake_corrupt_json_raises(tmp_path):
    path = tmp_path / HANDSHAKE_FILENAME
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(HandshakeError, match="不可解析"):
        read_handshake(path)


def test_read_handshake_missing_field_raises(tmp_path):
    path = tmp_path / HANDSHAKE_FILENAME
    path.write_text(json.dumps({"pid": 1, "port": 2}), encoding="utf-8")
    with pytest.raises(HandshakeError, match="缺字段"):
        read_handshake(path)


def test_read_handshake_rejects_bool_as_int(tmp_path):
    """bool 是 int 子类——端口/pid/version 不得被 true/false 冒充。"""
    path = tmp_path / HANDSHAKE_FILENAME
    path.write_text(
        json.dumps(
            {
                "pid": True,
                "port": 40000,
                "thread_id": "t",
                "protocol_version": 1,
                "started_at": "now",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(HandshakeError, match="应为 int"):
        read_handshake(path)


def test_clear_handshake_removes_file_and_is_idempotent(tmp_path):
    path = tmp_path / HANDSHAKE_FILENAME
    write_handshake(path, new_handshake(40000, "t"))
    clear_handshake(path)
    assert not path.exists()
    clear_handshake(path)  # 再删一次不抛


def test_is_stale_true_for_missing_file(tmp_path):
    assert is_stale(tmp_path / HANDSHAKE_FILENAME) is True


def test_is_stale_true_for_dead_pid(tmp_path):
    """残留握手文件：pid 已不在 → 陈废（前端据此忽略并重试）。"""
    path = tmp_path / HANDSHAKE_FILENAME
    write_handshake(path, new_handshake(40000, "t", pid=999_999_999))
    assert is_stale(path) is True


def test_is_stale_false_for_live_handshake(tmp_path):
    path = tmp_path / HANDSHAKE_FILENAME
    write_handshake(path, new_handshake(40000, "t", pid=os.getpid()))
    assert is_stale(path) is False


def test_is_stale_true_for_corrupt_file(tmp_path):
    path = tmp_path / HANDSHAKE_FILENAME
    path.write_text("garbage", encoding="utf-8")
    assert is_stale(path) is True


def test_protocol_server_dispatches_input_to_driver():
    driver = StubDriver()
    server = ProtocolServer(driver)
    messages = run(server.handle_text(json.dumps({"type": "input", "text": "今天要做什么呢？"})))
    assert driver.received == ["今天要做什么呢？"]
    assert messages == [{"type": "notice", "text": "ok"}]


def test_protocol_server_quit_returns_farewell_without_driver():
    driver = StubDriver()
    server = ProtocolServer(driver)
    messages = run(server.handle_text(json.dumps({"type": "quit"})))
    assert messages == [{"type": "farewell", "text": "再见"}]
    assert driver.received == []


def test_protocol_server_bad_json_returns_notice():
    server = ProtocolServer(StubDriver())
    messages = run(server.handle_text("{oops"))
    assert messages[0]["type"] == "notice"
    assert "不是合法 JSON" in messages[0]["text"]


def test_protocol_server_unknown_type_returns_notice():
    server = ProtocolServer(StubDriver())
    messages = run(server.handle_text(json.dumps({"type": "resume", "value": 1})))
    assert messages[0]["type"] == "notice"
    assert "不合协议" in messages[0]["text"]


def test_protocol_server_missing_field_returns_notice():
    server = ProtocolServer(StubDriver())
    messages = run(server.handle_text(json.dumps({"type": "input"})))
    assert messages[0]["type"] == "notice"


def test_is_quit_detects_farewell():
    assert is_quit([{"type": "farewell", "text": "再见"}]) is True
    assert is_quit([{"type": "notice", "text": "hi"}]) is False
    assert is_quit([]) is False


def test_transport_module_has_no_graph_dependency():
    """红线哨兵（ADR-0005/Q71）：传输层不得反向依赖图/节点——否则即倒退。"""
    source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "project_agent" / "transport.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "project_agent.nodes",
        "project_agent.graph",
        "project_agent.runtime",
        "project_agent.model_client",
        "project_agent.repl",
        "langgraph",
        "langchain_core",
    }
    assert imported & forbidden == set(), f"传输层不得依赖图/模型: {sorted(imported & forbidden)}"


def test_transport_module_imports_websockets_lazily():
    """Q39 红线同法：顶层不得 import 网络库（只允许函数体内延迟导入）。"""
    source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "project_agent" / "transport.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    top_imports: set[str] = set()
    for node in tree.body:  # 只看模块顶层
        if isinstance(node, ast.Import):
            top_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_imports.add(node.module)
    assert "websockets" not in top_imports, "顶层 import websockets 即倒退（须函数内延迟导入）"


def test_serve_end_to_end_random_port_and_handshake(tmp_path):
    """端到端（Q71 裁①③）：随机端口 bind → 握手文件携带真实端口与 thread_id
    → 前端读文件连上 → 一轮 input 收到 round_end → 断线后握手文件被清理。
    """
    import websockets

    from project_agent.transport import make_serve

    state_path = tmp_path / "state.db"
    path = handshake_path(state_path)
    driver = StubDriver([{"type": "notice", "text": "招呼"}])

    async def scenario() -> tuple[int, str, list[dict]]:
        serve = make_serve(driver, state_path=state_path, thread_id="t-e2e")
        task = asyncio.create_task(serve())
        # 等握手文件出现（后端 bind 完成）
        for _ in range(200):
            if path.exists():
                break
            await asyncio.sleep(0.01)
        handshake = read_handshake(path)
        async with websockets.connect(f"ws://127.0.0.1:{handshake.port}") as ws:
            await ws.send(json.dumps({"type": "input", "text": "你好"}, ensure_ascii=False))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, RuntimeError):
            pass
        return handshake.port, handshake.thread_id, [json.loads(raw)]

    port, thread_id, replies = run(scenario())
    assert isinstance(port, int) and port > 0
    assert thread_id == "t-e2e"
    assert replies[0]["type"] == "notice"
    assert replies[0]["text"] == "招呼"
    assert driver.received == ["你好"]
    assert not path.exists(), "会话结束须清理握手文件"

