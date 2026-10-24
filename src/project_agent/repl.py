"""REPL 宿主：终端 I/O、斜杠路由（零 LLM）、断点持有与渲染、/compact 手动压缩兜底。"""

from __future__ import annotations

from typing import Any

from project_agent.config import IO
from project_agent.fusion import fusion_update
from project_agent.nodes import run_compression_check

_BANNER = "Project Agent（01 骨架）。输入 /help 查看命令。"
_FAREWELL = "再见"
_TERMINAL_NOTICE = "构建已完成（终态）。输入 /exit 退出。"
_COMPACT_NOT_ENABLED = "压缩未启用（需 --cheap-model 接线）"

# 命令按长度降序前缀匹配（spec『路由』：斜杠命令前缀匹配，零 LLM）
_COMMANDS = ("/help", "/status", "/compact", "/exit")

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
    def __init__(
        self,
        app: Any,
        io: IO,
        thread_id: str,
        *,
        cheap_model: Any = None,
        shared_docs: Any = None,
    ) -> None:
        self._app = app
        self._io = io
        self._config = {"configurable": {"thread_id": thread_id}}
        self._last_state: dict[str, Any] = {}
        self._cheap_model = cheap_model
        self._shared_docs = shared_docs
        # /compact 产生的待并压缩批：下轮 invoke 携带进图（经 add_messages
        # reducer 归约——否则 checkpointer 里的历史永远未压）
        self._pending_compression: dict[str, Any] | None = None

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
        if command == "/compact":
            self._compact()
            return False
        self._io.write_line(f"未知命令 {text}。可用命令：{' '.join(_COMMANDS)}")
        return False

    def _compact(self) -> None:
        """/compact 手动兜底（08 票）：立即触发等价压缩（manual=True）。

        仍守 3 轮保护与两包上限；压缩结果（重排后消息批 + compacted_rounds）
        并入 REPL 持有状态——下轮 invoke 携带；不进主图。
        """
        if self._cheap_model is None:
            self._io.write_line(_COMPACT_NOT_ENABLED)
            return
        updates = run_compression_check(
            messages=self._last_state.get("actor_messages") or [],
            model=None,
            cheap_model=self._cheap_model,
            thread_id=str(self._config.get("configurable", {}).get("thread_id", "")),
            shared_docs=self._shared_docs,
            notes_version=int(self._last_state.get("notes_version") or 0),
            manual=True,
        )
        if updates is None:
            self._io.write_line("无可压缩轮次（3 轮保护或无候选）。")
            return
        self._last_state.update(updates)
        self._pending_compression = updates
        packs = updates.get("compacted_rounds") or []
        covered = sum(end - start + 1 for start, end in packs)
        self._io.write_line(f"已压缩 {covered} 轮（{len(packs)} 包）；磁盘【R#】原文不受影响。")

    def _run_turn(self, text: str) -> None:
        update = fusion_update(self._last_state, text)
        if not update:
            # FINISHED 终态（01 欠账 b）：不再融合不再 invoke
            self._io.write_line(_TERMINAL_NOTICE)
            return
        if self._pending_compression is not None:
            # 待并压缩批先行：头部单包/RemoveMessage 与新输入一起进图，
            # add_messages reducer 归约出压缩后历史（一次性，随后清空）
            pending = self._pending_compression
            self._pending_compression = None
            merged_batch = list(pending.get("actor_messages") or [])
            merged_batch.extend(update.get("actor_messages") or [])
            update = dict(pending)
            update["actor_messages"] = merged_batch
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
