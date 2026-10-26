"""传输层（UX-2 第二片，spec v2.2『传输层』）：WebSocket + 随机端口握手文件。

三裁（Q71）在此落地：

1. **随机端口 + 握手文件**：bind `127.0.0.1:0` 由 OS 分配；`{pid, port,
   thread_id, protocol_version, started_at}` 写进握手文件供前端读取。
2. **前端产物首次运行下载**：不在本模块（属 UX-3 片 4）；本层只提供
   `frontend_available()` 判定钩子。
3. **断线复用 thread_id 续跑**：握手文件带 thread_id；重连后同一
   checkpointer 同 thread，末态由 `_seed_state_from_checkpoint` 重建。

红线：本层零业务逻辑——只做"收上行 → 调 SessionDriver → 发下行"。
顶层不得 import 图/节点内部（AST 哨兵，与 messages.py 同法）。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from project_agent.messages import MessageError, decode

HANDSHAKE_FILENAME = "handshake.json"
PROTOCOL_VERSION = 1
_EXIT_MESSAGE_TYPE = "farewell"


@dataclass(frozen=True)
class Handshake:
    """随机端口发现文件的内容（前端据此连接）。"""

    pid: int
    port: int
    thread_id: str
    protocol_version: int
    started_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HandshakeError(Exception):
    """握手文件缺失 / 损坏 / 形状不符。"""


def handshake_path(state_path: Path) -> Path:
    """握手文件与断点库同目录（`--state` 同目录约定）。"""
    return Path(state_path).parent / HANDSHAKE_FILENAME


def write_handshake(path: Path, handshake: Handshake) -> None:
    """原子写握手文件（先写临时文件再替换，避免前端读到半截 JSON）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(handshake.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, target)


def read_handshake(path: Path) -> Handshake:
    """读并校验握手文件；损坏或形状不符 → HandshakeError。"""
    target = Path(path)
    if not target.exists():
        raise HandshakeError(f"握手文件不存在: {target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HandshakeError(f"握手文件不可解析: {exc}") from exc
    if not isinstance(data, dict):
        raise HandshakeError("握手文件必须是 JSON 对象")
    fields = ("pid", "port", "thread_id", "protocol_version", "started_at")
    missing = [key for key in fields if key not in data]
    if missing:
        raise HandshakeError(f"握手文件缺字段: {missing}")
    pid = data["pid"]
    port = data["port"]
    version = data["protocol_version"]
    for name, value in (("pid", pid), ("port", port), ("protocol_version", version)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise HandshakeError(f"握手文件 {name} 应为 int")
    for name in ("thread_id", "started_at"):
        if not isinstance(data[name], str):
            raise HandshakeError(f"握手文件 {name} 应为 str")
    return Handshake(
        pid=pid,
        port=port,
        thread_id=data["thread_id"],
        protocol_version=version,
        started_at=data["started_at"],
    )


def clear_handshake(path: Path) -> None:
    """会话结束清握手文件（残留文件由前端按 pid 识别后忽略）。"""
    target = Path(path)
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def _pid_alive(pid: int) -> bool:
    """进程存活判定（跨平台）：0/负值无意义，POSIX 用 signal 0，Windows 用 OpenProcess 语义近似。"""
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - Windows 专用分支
        # Windows 无 signal 0；用 tasklist 判定成本高，改判"是否本进程"
        return pid == os.getpid()
    try:  # pragma: no cover - POSIX 专用分支
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def is_stale(path: Path) -> bool:
    """握手文件是否陈废（所属进程已不在）。读不出形状也视为陈废。"""
    try:
        handshake = read_handshake(path)
    except HandshakeError:
        return True
    return not _pid_alive(handshake.pid)


def new_handshake(port: int, thread_id: str, *, pid: int | None = None) -> Handshake:
    """构造握手内容（`started_at` 取本地时间 ISO 串）。"""
    return Handshake(
        pid=os.getpid() if pid is None else pid,
        port=port,
        thread_id=thread_id,
        protocol_version=PROTOCOL_VERSION,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


class ProtocolServer:
    """把一条上行消息送进 SessionDriver，再把产生的下行消息送回前端。

    `driver` 只需满足 `handle_input(text) -> list[dict]`（ReplHost 即是）。
    """

    def __init__(self, driver: Any, *, host: str = "127.0.0.1") -> None:
        self._driver = driver
        self._host = host

    async def handle_text(self, raw: str) -> list[dict[str, Any]]:
        """收一条原始上行 JSON 文本 → 校验 → 分发 → 下行消息列表。"""
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            return [{"type": "notice", "text": f"上行消息不是合法 JSON: {exc}"}]
        try:
            message = decode(payload)
        except MessageError as exc:
            return [{"type": "notice", "text": f"上行消息不合协议: {exc}"}]
        return self._dispatch(message)

    def _dispatch(self, message: Mapping[str, Any]) -> list[dict[str, Any]]:
        if message["type"] == "quit":
            return [{"type": "farewell", "text": "再见"}]
        return list(self._driver.handle_input(message["text"]))


def is_quit(messages: list[dict[str, Any]]) -> bool:
    """本次输入是否导致会话终止（出现 farewell 即终止）。"""
    return any(m.get("type") == _EXIT_MESSAGE_TYPE for m in messages)


def make_serve(
    driver: Any, *, state_path: Path, thread_id: str, host: str = "127.0.0.1"
) -> Callable[..., Any]:
    """返回一个 async serve 函数（延迟 import websockets——顶层不引网络库）。

    用法：`await make_serve(...)()` 或 `asyncio.run(make_serve(...)())`。
    """
    path = handshake_path(state_path)
    server = ProtocolServer(driver, host=host)

    async def serve() -> None:
        import websockets  # 延迟导入：顶层不引网络库（Q39 红线同法）

        async def handler(websocket: Any) -> None:
            async for raw in websocket:
                messages = await server.handle_text(raw if isinstance(raw, str) else raw.decode("utf-8"))
                for message in messages:
                    await websocket.send(json.dumps(message, ensure_ascii=False))
                if is_quit(messages):
                    break

        async with websockets.serve(handler, host, 0) as ws_server:
            port = _bound_port(ws_server)
            write_handshake(path, new_handshake(port, thread_id))
            try:
                await ws_server.wait_closed()
            finally:
                clear_handshake(path)

    return serve


def _bound_port(ws_server: Any) -> int:
    """从 websockets Server 上取 bind 后的实际端口（版本间形态差异兜底）。"""
    sockets = getattr(ws_server, "sockets", None)
    if sockets:
        return int(sockets[0].getsockname()[1])
    raise RuntimeError("无法取 WebSocket 绑定端口（websockets 版本形态不符）")
