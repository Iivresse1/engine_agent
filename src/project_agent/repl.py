"""REPL 宿主：终端 I/O、斜杠路由（零 LLM）、断点持有与渲染。"""

from __future__ import annotations

from typing import Any

from project_agent.config import IO
from project_agent.fusion import fusion_update

_BANNER = "Project Agent（01 骨架）。输入 /help 查看命令。"
_FAREWELL = "再见"
_TERMINAL_NOTICE = "构建已完成（终态）。输入 /exit 退出。"

# 命令按长度降序前缀匹配（spec『路由』：斜杠命令前缀匹配，零 LLM）
_COMMANDS = ("/help", "/status", "/exit")

_STATUS_FIELDS = (
    "task_brief",
    "build_way",
    "guidance_mode",
    "user_mode",
    "guidance_pref",
    "decision_mode",
    "skill_packs",
    "turn_end_reason",
)


class ReplHost:
    def __init__(self, app: Any, io: IO, thread_id: str) -> None:
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

    def _dispatch(self, text: str) -> bool:
        """斜杠命令前缀匹配分发（零 LLM）。返回 True 表示退出。"""
        command = next((c for c in sorted(_COMMANDS, key=len, reverse=True) if text.startswith(c)), None)
        if command == "/exit":
            self._io.write_line(_FAREWELL)
            return True
        if command == "/help":
            self._io.write_line("可用命令：" + " ".join(_COMMANDS))
            return False
        if command == "/status":
            self._status()
            return False
        self._io.write_line(f"未知命令 {text}。可用命令：{' '.join(_COMMANDS)}")
        return False

    def _run_turn(self, text: str) -> None:
        update = fusion_update(self._last_state, text)
        if not update:
            # FINISHED 终态（01 欠账 b）：不再融合不再 invoke
            self._io.write_line(_TERMINAL_NOTICE)
            return
        result = dict(self._app.invoke(update, self._config))
        self._last_state = result

        reason = result.get("turn_end_reason") or "未记录"
        payload = result.get("turn_end_payload") or {}
        self._io.write_line(f"断点 · {reason}")
        for key, value in payload.items():
            self._io.write_line(f"  {key}: {value}")

    def _status(self) -> None:
        if not self._last_state:
            self._io.write_line("尚无会话状态。")
            return
        for field in _STATUS_FIELDS:
            self._io.write_line(f"{field}: {self._last_state.get(field, '')}")
