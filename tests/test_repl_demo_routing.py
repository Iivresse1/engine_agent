"""11 票切片 3：REPL 混合路由接线（验收 3/5 接缝）。

仅当 last_state 的 demo_phase=="building" 才走三层；error_return →
{"demo_messages":[HumanMessage(text)], "demo_loop_count": 旧+1} + invoke；
normal → fusion_update 原路径（普通文本默认去活跃 agent）。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from project_agent.repl import ReplHost
from tests.doubles.fake_model import ScriptedModel
from tests.doubles.scripted_io import ScriptedIO


class StubApp:
    """记录 invoke 的 update；返回 demo 构建中的状态（round 断点）。"""

    def __init__(self, base: dict | None = None) -> None:
        self.base = dict(base or {})
        self.updates: list[dict] = []
        self.state: dict = {}

    def invoke(self, update, config):
        self.updates.append(dict(update))
        self.state = {
            **self.base,
            **self.state,
            **update,
            "turn_end_reason": "round",
            "turn_end_payload": {"round_output": "ok", "todo_board": []},
        }
        return dict(self.state)


def _host(stub: StubApp, lines: list[str], **kwargs) -> tuple[ReplHost, ScriptedIO]:
    io = ScriptedIO([*lines, "/exit"])
    return ReplHost(stub, io, "t-repl-11", **kwargs), io


def test_normal_text_while_demo_building_uses_fusion_path():
    """普通文本默认去活跃 agent：仍走 fusion_update（actor_messages）。"""
    stub = StubApp({"demo_phase": "building", "task_complete": True})
    host, _io = _host(stub, ["第一轮", "把按钮改蓝"])
    host.run()
    # 第 2 条输入走原路径：融合进主线历史，而非 demo_messages
    assert stub.updates[1] == {"actor_messages": [HumanMessage(content="把按钮改蓝")]}


def test_traceback_while_demo_building_returns_to_demo_agent_and_counts():
    """贴 Traceback 无命令直接路由进 DemoAgent：融合 demo_messages + 计数++。"""
    stub = StubApp({"demo_phase": "building", "task_complete": True})
    host, _io = _host(stub, ["第一轮", "Traceback (most recent call last):\nNameError: x"])
    host.run()
    update = stub.updates[1]
    assert update["demo_loop_count"] == 1
    assert len(update["demo_messages"]) == 1
    assert isinstance(update["demo_messages"][0], HumanMessage)
    assert "NameError" in update["demo_messages"][0].content


def test_repeated_errors_increment_demo_loop_count():
    """修复循环计数：每贴一次报错 +1（REPL 融合时自增）。"""
    stub = StubApp({"demo_phase": "building", "task_complete": True})
    host, _io = _host(
        stub,
        ["第一轮", "ZeroDivisionError: x", "Traceback (most recent call last): y"],
    )
    host.run()
    assert stub.updates[1]["demo_loop_count"] == 1
    assert stub.updates[2]["demo_loop_count"] == 2


def test_traceback_when_demo_not_active_goes_normal_path():
    """特征预筛需 demo 阶段活跃：非 demo 时 Traceback 仍走普通融合。"""
    stub = StubApp({"demo_phase": "skipped", "task_complete": True})
    host, _io = _host(stub, ["第一轮", "Traceback (most recent call last): x"])
    host.run()
    assert "actor_messages" in stub.updates[1]
    assert "demo_messages" not in stub.updates[1]


def test_llm_classifier_binary_routes_error_text():
    """窄分类兜底二分：分类器说"报错"→ error_return；普通→ normal。"""
    stub = StubApp({"demo_phase": "building", "task_complete": True})
    classifier = ScriptedModel(["这是报错回传", "普通输入"])
    host, _io = _host(
        stub,
        ["第一轮", "跑起来就挂了", "继续推进"],
        error_classifier=classifier,
    )
    host.run()
    assert stub.updates[1]["demo_loop_count"] == 1
    assert "demo_messages" in stub.updates[1]
    assert "actor_messages" in stub.updates[2]
    # 分类器两次调用（role=router）
    assert [call["role"] for call in classifier.calls] == ["router", "router"]


def test_error_return_renders_round_breakpoint():
    """error_return 仍走主图 invoke 并渲染断点（非终态）。"""
    stub = StubApp({"demo_phase": "building", "task_complete": True})
    host, io = _host(stub, ["第一轮", "SyntaxError: invalid syntax"])
    host.run()
    assert any("断点 · round" in line for line in io.outputs)


def test_fifth_pasted_error_breaks_with_loop_exhausted(tmp_path):
    """验收 5 端到端：真图 REPL 回放——第 5 次贴报错 → loop_exhausted 断点。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from project_agent.graph import build_graph

    main = ScriptedModel(["第四轮修复", "第五轮前修复"])
    app = build_graph(
        checkpointer=InMemorySaver(), model=main, workspace_root=tmp_path
    )
    cfg = {"configurable": {"thread_id": "t-demo-loop"}}
    app.invoke(
        {
            "task_brief": "做个记账 CLI",
            "build_way": "way3",
            "todos": [{"content": "写 README", "status": "completed"}],
            "task_complete": True,
            "demo_phase": "building",
            "demo_loop_count": 4,
            "demo_messages": [HumanMessage(content="第 4 次报错")],
            "actor_messages": [HumanMessage(content="主线")],
        },
        cfg,
    )

    io = ScriptedIO(["继续修一下", "Traceback (most recent call last): fifth"])
    host = ReplHost(app, io, "t-demo-loop")
    host.run()

    out = "\n".join(io.outputs)
    assert "断点 · loop_exhausted" in out
    assert "demo 环计数 5" in out
    state = app.get_state(cfg).values
    assert state["demo_loop_count"] == 5
    assert len(state["demo_messages"]) >= 2
