"""REPL 宿主回放：首启一次、斜杠零 LLM 分发、断点持有与渲染。"""

from __future__ import annotations

import json

import pytest

from project_agent.config import ConfigStore, ensure_config
from project_agent.graph import build_graph, new_thread_id
from project_agent.repl import ReplHost
from tests.doubles.scripted_io import ScriptedIO

pytestmark = pytest.mark.replay


def _onboarding_answers() -> list[str]:
    return ["deepseek-chat", "sk-test", "", ""]


def test_first_run_onboarding_then_zero_questions_on_restart(workspace):
    io = ScriptedIO(_onboarding_answers())
    cfg = ensure_config(ConfigStore(workspace.config_path), io)
    assert cfg.main_model == "deepseek-chat"
    assert cfg.api_key == "sk-test"
    assert workspace.config_path.exists()

    data = json.loads(workspace.config_path.read_text(encoding="utf-8"))
    assert data == {
        "main_model": "deepseek-chat",
        "api_key": "sk-test",
        "base_url": "",
        "sub_model": "",
    }

    # 重启：已有配置，零提问直达
    io2 = ScriptedIO([])
    cfg2 = ensure_config(ConfigStore(workspace.config_path), io2)
    assert cfg2 == cfg
    assert io2.outputs == []


def test_repl_session_rounds_slash_and_status(workspace):
    io = ScriptedIO(
        _onboarding_answers()
        + [
            "我想做一个记账 CLI",
            "/status",
            "我不了解编程",
            "自动每轮",
            "AI 自动审核",
            "默认技能包",
            "/status",
            "嗯",  # 首入 build_ways：发 choice 断点
            "/status",
            "用完整文档",  # 决议通道输入 → build_way 写定
            "/status",
            "/nope",
            "/exit",
        ]
    )
    ensure_config(ConfigStore(workspace.config_path), io)

    app = build_graph()
    host = ReplHost(app, io, new_thread_id())
    host.run()

    out = "\n".join(io.outputs)
    # 非斜杠输入进主图，断点渲染
    assert "断点 · round" in out
    # 四问渲染
    assert "断点 · question" in out
    assert "你的编程基础？" in out
    assert "我不了解编程" in out  # Q1 选项
    # /status 展示仪表盘
    assert "task_brief: 我想做一个记账 CLI" in out
    assert "user_mode: novice" in out
    # choice 断点渲染：4 选项 + 推荐 + 一句话理由
    assert "断点 · choice:build_way" in out
    assert "轻 grill" in out
    assert "个人作品有沉淀不臃肿" in out
    # 决议后 build_way 已置位
    assert "build_way: way4" in out
    # 未知斜杠零 LLM：报错并列出可用命令
    assert "未知命令 /nope" in out
    assert "/help" in out
    assert "/status" in out
    # /exit 干净退出
    assert "再见" in out


def test_eof_ends_repl_gracefully(workspace):
    io = ScriptedIO(_onboarding_answers())
    ensure_config(ConfigStore(workspace.config_path), io)

    host = ReplHost(build_graph(), ScriptedIO([]), new_thread_id())
    host.run()  # EOF（read_line 返回 None）不抛异常


def test_repl_renders_missing_reason_as_unrecorded(workspace):
    """回归（冒烟发现）：轮终未写 turn_end_reason 时渲染『未记录』而非沿用旧值。"""
    ensure_config(ConfigStore(workspace.config_path), ScriptedIO(_onboarding_answers()))

    class StubApp:
        def invoke(self, update, config):
            return {"actor_messages": list(update.get("actor_messages", []))}

    io = ScriptedIO(["hello", "/exit"])
    ReplHost(StubApp(), io, new_thread_id()).run()
    assert "断点 · 未记录" in "\n".join(io.outputs)


def test_slash_commands_match_by_prefix(workspace):
    """spec『路由』：斜杠命令前缀匹配（零 LLM）——带尾随词也命中。"""
    ensure_config(ConfigStore(workspace.config_path), ScriptedIO(_onboarding_answers()))

    io = ScriptedIO(["/status extra words", "/exit now please"])
    ReplHost(build_graph(), io, new_thread_id()).run()
    out = "\n".join(io.outputs)
    assert "未知命令" not in out  # 前缀命中，不是未知
    assert "再见" in out  # "/exit now please" 命中退出
