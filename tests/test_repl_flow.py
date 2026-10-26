"""REPL 宿主回放：首启一次、斜杠零 LLM 分发、断点持有与渲染。"""

from __future__ import annotations

import pytest

from project_agent.config import ConfigStore, ensure_config, parse_env
from project_agent.graph import build_graph, new_thread_id
from project_agent.repl import ReplHost
from tests.doubles.scripted_io import ScriptedIO

pytestmark = pytest.mark.replay


def _onboarding_answers() -> list[str]:
    return ["deepseek-chat", "sk-test", "", "", ""]


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    """隔离密钥发现：指向不存在的密钥文件（Q64 兜底路径）。

    该兜底会在配置缺失时先探桌面 storage/apikey.txt；本机确实存在该文件，
    不隔离则问卷问题序被打乱、测试输入整体错位。用 `PROJECT_AGENT_API_KEY_FILE`
    指向空路径最直接（显式覆盖优先于任何探测根）。
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PROJECT_AGENT_API_KEY_FILE", str(home / "no-such-apikey.txt"))
    return home


def test_first_run_onboarding_then_zero_questions_on_restart(workspace, isolated_home):
    io = ScriptedIO(_onboarding_answers())
    cfg = ensure_config(ConfigStore(workspace.config_path), io)
    assert cfg.main_model == "deepseek-chat"
    assert cfg.api_key == "sk-test"
    assert workspace.config_path.exists()

    # v1.5：.env 格式落盘（KEY=VALUE 平面）；14 票新增 decision_mode 键
    values = parse_env(workspace.config_path.read_text(encoding="utf-8"))
    assert values == {
        "main_model": "deepseek-chat",
        "api_key": "sk-test",
        "base_url": "",
        "sub_model": "",
        "decision_mode": "ai_review",
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
            "我想做一个记账 CLI",  # 首条自由文本 → 简报写定（14 票）
            "/status",
            "嗯",  # 首入 build_ways：发 choice 断点
            "/status",
            "用完整文档",  # 决议通道输入 → build_way 写定 → 指引一问
            "/status",
            "需要",  # 指引答案 → guidance_pref/user_mode/guidance_mode 落盘
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
    # 14 票重编排：开场提示语 + 简报 round + 指引一问 question 断点
    assert "今天要做什么呢？" in out
    assert "任务简报已记录：我想做一个记账 CLI" in out
    assert "断点 · question" in out
    assert "需要每轮给出指引帮助更好的理解项目吗" in out
    assert "边构建边学" in out
    assert "我自己看得懂" in out  # 指引选项主体
    # /status 展示仪表盘
    assert "task_brief: 我想做一个记账 CLI" in out
    # 指引答案推导 user_mode（auto → novice，14 票）
    assert "user_mode: novice" in out
    assert "guidance_pref: auto" in out
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


def test_finished_terminal_state_notices_and_does_not_invoke(workspace):
    """01 欠账 b：FINISHED 终态——打通知、不 invoke 不融合。"""
    ensure_config(ConfigStore(workspace.config_path), ScriptedIO(_onboarding_answers()))

    class StubApp:
        def __init__(self) -> None:
            self.invocations = 0

        def invoke(self, update, config):
            self.invocations += 1
            return {"turn_end_reason": "finished", "turn_end_payload": {"delivery_paths": {}}}

    stub = StubApp()
    io = ScriptedIO(["hello", "再聊聊", "/exit"])
    ReplHost(stub, io, new_thread_id()).run()
    out = "\n".join(io.outputs)
    assert "构建已完成（终态）。输入 /exit 退出。" in out
    assert stub.invocations == 1  # FINISHED 后再输入：invoke 计数不增


def test_slash_commands_match_by_prefix(workspace):
    """spec『路由』：斜杠命令前缀匹配（零 LLM）——带尾随词也命中。"""
    ensure_config(ConfigStore(workspace.config_path), ScriptedIO(_onboarding_answers()))

    io = ScriptedIO(["/status extra words", "/exit now please"])
    ReplHost(build_graph(), io, new_thread_id()).run()
    out = "\n".join(io.outputs)
    assert "未知命令" not in out  # 前缀命中，不是未知
    assert "再见" in out  # "/exit now please" 命中退出
