"""CLI 入口：project-agent 控制台脚本或 python -m project_agent.cli。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from project_agent.config import ConfigStore, IO, ensure_config
from project_agent.graph import build_graph, new_thread_id, sqlite_checkpointer
from project_agent.repl import ReplHost


class ConsoleIO:
    def read_line(self) -> str | None:
        try:
            return input()
        except EOFError:
            return None

    def write_line(self, text: str) -> None:
        print(text)


def _force_utf8_stdio() -> None:
    """管道/重定向态统一 UTF-8（交互 TTY 走控制台 API 本就全 Unicode）。

    Windows 上被管道时 Python 默认用本地代码页（GBK），中文必乱；
    交互式终端不受此影响。管道喂入/喂出本应用一律按 UTF-8。
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def default_config_path() -> Path:
    return Path.home() / ".project-agent" / "config.json"


def _session_path(state_path: Path) -> Path:
    return state_path.with_suffix(state_path.suffix + ".session.json")


def _load_or_new_thread(session_path: Path, *, fresh: bool) -> str:
    """跨进程续跑：thread_id 持久化在会话文件里，重启后接续同一断点序列。"""
    if not fresh and session_path.exists():
        data = json.loads(session_path.read_text(encoding="utf-8"))
        thread_id = data.get("thread_id")
        if thread_id:
            return thread_id
    thread_id = new_thread_id()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps({"thread_id": thread_id}, ensure_ascii=False), encoding="utf-8"
    )
    return thread_id


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="project-agent")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="断点持久化数据库（默认：配置同目录 state.db）",
    )
    parser.add_argument(
        "--new-session", action="store_true", help="开新 thread（不接续旧断点）"
    )
    args = parser.parse_args(argv)

    _force_utf8_stdio()

    state_path = args.state or args.config.with_name("state.db")
    io: IO = ConsoleIO()
    ensure_config(ConfigStore(args.config), io)
    thread_id = _load_or_new_thread(_session_path(state_path), fresh=args.new_session)

    with sqlite_checkpointer(state_path) as checkpointer:
        # TODO（真模型票）：MeteredModel(model, TokenLedger(--state 同目录
        # ledger.json)) 包装后传入——05 骨架 CLI 无真模型，主环 inert。
        app = build_graph(checkpointer=checkpointer)
        ReplHost(app, io, thread_id).run()


if __name__ == "__main__":
    main()
