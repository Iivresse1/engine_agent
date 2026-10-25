"""CLI 入口：engine 控制台脚本或 python -m project_agent.cli。

v1.5 接线票：真模型入图——config.env（ensure_config）→ build_model_runtime
装配 MeteredModel/SharedDocs/AskBypass → build_graph(model=..., cheap_model=...,
workspace_root=cwd)：verifier 环闭合、压缩横切挂上、/compact 与 /ask-for-help
可用；账单落 --state 同目录 ledger.json。

14 票（UX-1）：命令名 engine（旧名 project-agent 废弃）；--state 默认
**每项目** `<cwd>/.project-agent/state.db`（config 仍全局）；首启无配置先试
tkinter 窗口（gui_config），失败退终端问卷；ReplHost 种子注入
decision_mode（配置开关）/skill_packs（默认包）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from project_agent.config import IO, AppConfig, ConfigStore, ensure_config
from project_agent.graph import build_graph, new_thread_id, sqlite_checkpointer
from project_agent.gui_config import collect_config_gui
from project_agent.repl import ReplHost
from project_agent.runtime import build_model_runtime


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
    """全局应用级配置（v1.5：.env 密钥惯例格式；旧 config.json 自动迁移）。"""
    return Path.home() / ".project-agent" / "config.env"


def default_state_path() -> Path:
    """每项目断点库（14 票：cwd/.project-agent/；session/ledger 同目录）。"""
    return Path.cwd() / ".project-agent" / "state.db"


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


def _first_run_config(store: ConfigStore, io: IO) -> AppConfig:
    """首启取配置：tkinter 窗口优先，取消/不可用 → 终端问卷 fallback。"""
    gui_config = collect_config_gui()
    if gui_config is not None:
        store.save(gui_config)
        return gui_config
    return ensure_config(store, io)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="engine")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="断点持久化数据库（默认：当前目录 .project-agent/state.db）",
    )
    parser.add_argument(
        "--new-session", action="store_true", help="开新 thread（不接续旧断点）"
    )
    args = parser.parse_args(argv)

    _force_utf8_stdio()

    state_path = args.state or default_state_path()
    io: IO = ConsoleIO()
    store = ConfigStore(args.config)
    config = store.load() or _first_run_config(store, io)
    thread_id = _load_or_new_thread(_session_path(state_path), fresh=args.new_session)

    with sqlite_checkpointer(state_path) as checkpointer:
        runtime = build_model_runtime(
            config,
            ledger_path=state_path.with_name("ledger.json"),
            workspace_root=Path.cwd(),
            thread_id=thread_id,
        )
        app = build_graph(
            checkpointer=checkpointer,
            model=runtime.model,
            cheap_model=runtime.cheap_model,
            workspace_root=Path.cwd(),
        )
        ReplHost(
            app,
            io,
            thread_id,
            cheap_model=runtime.cheap_model,
            shared_docs=runtime.shared_docs,
            ask_bypass=runtime.ask_bypass,
            initial_dashboard={
                "decision_mode": config.decision_mode,
                "skill_packs": ["default"],
            },
        ).run()


if __name__ == "__main__":
    main()
