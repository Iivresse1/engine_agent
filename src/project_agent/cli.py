"""CLI 入口：project-agent 控制台脚本或 python -m project_agent.cli。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from project_agent.config import ConfigStore, ensure_config
from project_agent.graph import build_graph, new_thread_id
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="project-agent")
    parser.add_argument("--config", type=Path, default=default_config_path())
    args = parser.parse_args(argv)

    _force_utf8_stdio()

    io: Any = ConsoleIO()
    ensure_config(ConfigStore(args.config), io)
    app = build_graph()
    ReplHost(app, io, new_thread_id()).run()


if __name__ == "__main__":
    main()
