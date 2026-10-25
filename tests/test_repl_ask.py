"""10 票切片 2：REPL /ask-for-help 旁路（工作流守卫/三态输出/不进主图）。"""

from __future__ import annotations

from project_agent.ask_agent import AskBypass
from project_agent.repl import ReplHost
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel
from tests.doubles.scripted_io import ScriptedIO


class _StubApp:
    def __init__(self) -> None:
        self.invocations = 0

    def invoke(self, update, config):
        self.invocations += 1
        return {"turn_end_reason": "round", "turn_end_payload": {"round_output": "ok"}}


def _host(tmp_path, lines, *, build_way=None, ask_bypass=None, app=None):
    io = ScriptedIO(lines)
    host = ReplHost(
        app or _StubApp(),
        io,
        "t-repl-ask",
        shared_docs=SharedDocs(tmp_path),
        ask_bypass=ask_bypass,
    )
    if build_way is not None:
        host._last_state = {"build_way": build_way}
    return host, io


def test_repl_ask_for_help_outside_workflow_unavailable(tmp_path):
    """/ask-for-help 仅工作流内可用：build_way 未设 → 不可用提示。"""
    model = ScriptedModel([])  # 不应被调用
    bypass = AskBypass(model, SharedDocs(tmp_path), "t-ask")
    app = _StubApp()
    host, io = _host(tmp_path, ["/ask-for-help 技术栈？", "/exit"], ask_bypass=bypass, app=app)
    host.run()
    out = "\n".join(io.outputs)
    assert "仅项目工作流内可用" in out
    assert model.calls == []
    assert host._last_state == {}


def test_repl_ask_for_help_inside_workflow_writes_answer(tmp_path):
    """工作流内（build_way 已设）→ 旁路作答直写终端；不进主图不写 state。"""
    model = ScriptedModel(["项目用的是 React。"])
    bypass = AskBypass(model, SharedDocs(tmp_path), "t-ask")
    app = _StubApp()
    host, io = _host(
        tmp_path, ["/ask-for-help 前端用什么？", "/exit"], build_way="way1", ask_bypass=bypass, app=app
    )
    before = dict(host._last_state)
    host.run()
    out = "\n".join(io.outputs)
    assert "项目用的是 React。" in out
    assert app.invocations == 0  # 不进主图
    assert host._last_state == before  # 不写 state
    assert model.calls[0]["role"] == "ask_agent"
    assert "问题：前端用什么？" in model.calls[0]["messages"][-1]["content"]


def test_repl_ask_for_help_unwired_without_model(tmp_path):
    """工作流内但旁路未接线（ask_bypass=None）→ 提示需 model。"""
    app = _StubApp()
    host, io = _host(tmp_path, ["/ask-for-help 技术栈？", "/exit"], build_way="way1", app=app)
    host.run()
    out = "\n".join(io.outputs)
    assert "旁路未接线（需 model）" in out
    assert app.invocations == 0


def test_repl_ask_for_help_empty_question_shows_usage(tmp_path):
    """空问题 → 用法提示，零模型调用。"""
    model = ScriptedModel([])
    bypass = AskBypass(model, SharedDocs(tmp_path), "t-ask")
    host, io = _host(
        tmp_path, ["/ask-for-help   ", "/exit"], build_way="way1", ask_bypass=bypass
    )
    host.run()
    out = "\n".join(io.outputs)
    assert "用法：/ask-for-help" in out
    assert model.calls == []


def test_repl_help_lists_ask_for_help(tmp_path):
    host, io = _host(tmp_path, ["/help", "/exit"])
    host.run()
    assert "/ask-for-help" in "\n".join(io.outputs)
