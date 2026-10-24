"""REPL 宿主：终端 I/O、斜杠路由（零 LLM）、断点持有与渲染。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from project_agent.fusion import fusion_update

_BANNER = "Project Agent（01 骨架）。输入 /help 查看命令。"
_COMMANDS = ("/help", "/status", "/exit")
_FAREWELL = "再见"

_STATUS_FIELDS = ("task_brief", "build_way", "guidance_mode", "turn_end_reason")


class ReplHost:
    def __init__(self, app: Any, io: Any, thread_id: str) -> None:
        self._app = app
        self._io = io
        self._config = {"configurable": {"thread_id": thread_id}}
        self._last_state: dict[str, Any] = {}

    def run(self) -> None:
        self._io.write_line(_BANNER)
        while True:
            line = self._io.read_line()
            if line is None:  # EOF
                self._io.write_line(_FAREWELL)
                return
            text = line.strip()
            if not text:
                continue
            if text.startswith("/"):
                if self._dispatch(text):
                    return
                continue
            self._run_turn(text)

    def _dispatch(self, command: str) -> bool:
        """斜杠命令分发（前缀匹配，零 LLM）。返回 True 表示退出。"""
        if command == "/exit":
            self._io.write_line(_FAREWELL)
            return True
        if command == "/help":
            self._io.write_line("可用命令：" + " ".join(_COMMANDS))
            return False
        if command == "/status":
            self._status()
            return False
        self._io.write_line(f"未知命令 {command}。可用命令：{' '.join(_COMMANDS)}")
        return False

    def _run_turn(self, text: str) -> None:
        update = fusion_update(self._last_state, text)
        if not update:
            # FINISHED 终态：01 骨架仍融合主线；终态旁路语义在后续票完整化
            update = {"actor_messages": [HumanMessage(content=text)]}
        result = dict(self._app.invoke(update, self._config))
        self._last_state = result

        reason = result.get("turn_end_reason") or "未记录"
        payload = result.get("turn_end_payload") or {}
        self._io.write_line(f"轮终 · {reason}")
        for key, value in payload.items():
            self._io.write_line(f"  {key}: {value}")

    def _status(self) -> None:
        if not self._last_state:
            self._io.write_line("尚无会话状态。")
            return
        for field in _STATUS_FIELDS:
            self._io.write_line(f"{field}: {self._last_state.get(field, '')}")
