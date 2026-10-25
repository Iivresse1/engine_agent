"""11 票切片 2：DemoAgent 节点（验收 2/5）+ SharedDocs.write_any。

ADR-0003：demo 生成 + 运行指南落工作区；运行权在用户——响应含"运行：{cmd}"
只产提示，绝不调 ShellTool（shell 零调用）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_demo_agent_node
from project_agent.routing import LOOP_EXHAUSTED, _after_demo
from project_agent.shared_docs import SharedDocs
from project_agent.tools.approval import ApprovalResult
from project_agent.tools.knobs import ShellKnobs
from project_agent.tools.shell_policy import ShellPolicy
from project_agent.tools.shell_tool import ShellTool
from tests.doubles.fake_model import ScriptedModel
from tests.doubles.fake_shell import RecordingShell


class DenyApproval:
    def __call__(self, request) -> ApprovalResult:  # pragma: no cover - 不应被调用
        return ApprovalResult(approved=False)


DONE_TODOS = [{"content": "写 README", "status": "completed"}]
DEMO_STATE = {
    "task_brief": "做个记账 CLI",
    "build_way": "way3",
    "todos": DONE_TODOS,
    "task_complete": True,
    "demo_phase": "building",
}


def _cfg(thread: str = "t-demo") -> dict:
    return {"configurable": {"thread_id": thread}}


def _shell_tool(tmp_path: Path) -> tuple[ShellTool, RecordingShell]:
    runner = RecordingShell()
    tool = ShellTool(
        policy=ShellPolicy(knobs=ShellKnobs(), workspace_root=tmp_path),
        approval=DenyApproval(),
        shell_runner=runner,
    )
    return tool, runner


# —— SharedDocs.write_any：无白名单（demo 文件名自由），仅拦 ".." ——


def test_write_any_arbitrary_path_without_whitelist(tmp_path):
    docs = SharedDocs(tmp_path)
    assert docs.write_any("demo/main.py", "print('hi')\n") is True
    assert (tmp_path / "demo" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_write_any_creates_nested_parents(tmp_path):
    docs = SharedDocs(tmp_path)
    assert docs.write_any("demo/scripts/run.md", "# 运行指南\n") is True
    assert (tmp_path / "demo" / "scripts" / "run.md").is_file()


def test_write_any_rejects_parent_escape(tmp_path):
    docs = SharedDocs(tmp_path)
    assert docs.write_any("../escape.md", "x") is False
    assert docs.write_any("demo/../../escape.md", "x") is False
    assert not (tmp_path.parent / "escape.md").exists()


# —— 消息形态：任务行（含概览与报错上下文）+ demo_messages 历史 ——


def test_demo_node_message_shape_and_role(tmp_path):
    model = ScriptedModel(["demo 已生成。"])
    node = make_demo_agent_node(model, shared_docs=SharedDocs(tmp_path))
    state = dict(DEMO_STATE)
    state["demo_messages"] = [HumanMessage(content="上一轮报错")]
    updates = node(state, _cfg("dm-1"))

    call = model.calls[0]
    assert call["role"] == "demo_agent"
    assert call["thread_id"] == "dm-1"
    first = call["messages"][0]
    assert first["role"] == "user"
    assert "任务：为已完成的交付物生成可运行 demo 与运行指南。" in first["content"]
    assert "交付物：交付物集 3 份已就绪" in first["content"]
    assert "报错上下文：上一轮报错" in first["content"]
    # 历史转 dict 追加在任务行之后
    assert {"role": "user", "content": "上一轮报错"} in call["messages"][1:]
    # 产出：AIMessage 进 demo_messages + round 断点
    assert isinstance(updates["demo_messages"][0], AIMessage)
    assert updates["demo_messages"][0].content == "demo 已生成。"
    assert updates["turn_end_reason"] == "round"
    assert "demo 已生成。" in updates["turn_end_payload"]["round_output"]


def test_demo_node_no_error_context_says_none(tmp_path):
    model = ScriptedModel(["ok"])
    node = make_demo_agent_node(model, shared_docs=SharedDocs(tmp_path))
    node(dict(DEMO_STATE), _cfg("dm-2"))
    assert "报错上下文：无" in model.calls[0]["messages"][0]["content"]


# —— 生成物落盘（"写入：{文件名}\n{内容}" → write_any） ——


def test_demo_node_writes_generated_files(tmp_path):
    response = "写入：demo/main.py\nprint('hello demo')\n写入：demo/运行指南.md\n# 如何运行\npython demo/main.py"
    model = ScriptedModel([response])
    node = make_demo_agent_node(model, shared_docs=SharedDocs(tmp_path))
    node(dict(DEMO_STATE), _cfg("dm-3"))
    assert (tmp_path / "demo" / "main.py").read_text(encoding="utf-8") == "print('hello demo')"
    assert "python demo/main.py" in (tmp_path / "demo" / "运行指南.md").read_text(
        encoding="utf-8"
    )


# —— ADR-0003：运行权在用户（提示出现 + shell 零调用） ——


def test_demo_node_run_command_becomes_user_prompt_and_shell_never_called(tmp_path):
    response = "写入：demo/main.py\nprint('hi')\n运行：python demo/main.py"
    model = ScriptedModel([response])
    node = make_demo_agent_node(model, shared_docs=SharedDocs(tmp_path))
    tool, runner = _shell_tool(tmp_path)
    updates = node(dict(DEMO_STATE), _cfg("dm-4"))
    round_output = updates["turn_end_payload"]["round_output"]
    assert "运行权在用户（ADR-0003）：请自行执行 python demo/main.py" in round_output
    # 节点不持有也不调用 ShellTool：运行类命令零执行（ShellTool 存在但未被触达）
    assert runner.calls == []
    assert tool is not None


def test_demo_node_without_run_command_has_no_user_prompt(tmp_path):
    model = ScriptedModel(["写入：demo/main.py\nprint('hi')"])
    node = make_demo_agent_node(model, shared_docs=SharedDocs(tmp_path))
    updates = node(dict(DEMO_STATE), _cfg("dm-5"))
    assert "运行权在用户" not in updates["turn_end_payload"]["round_output"]


# —— 报错修复循环：demo_messages 尾部报错进上下文 ——


def test_demo_node_reads_pasted_error_from_tail(tmp_path):
    model = ScriptedModel(["已修复：改用 argparse。"])
    node = make_demo_agent_node(model, shared_docs=SharedDocs(tmp_path))
    state = dict(DEMO_STATE)
    state["demo_messages"] = [
        HumanMessage(content="请生成 demo"),
        AIMessage(content="写入：demo/main.py\nprint('hi')"),
        HumanMessage(content="Traceback (most recent call last):\nNameError: x"),
    ]
    node(state, _cfg("dm-6"))
    prompt = model.calls[0]["messages"][0]["content"]
    assert "报错上下文：Traceback (most recent call last):" in prompt


# —— 条件边 _after_demo：计数封顶 5 → LOOP_EXHAUSTED，否则 END ——


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"demo_loop_count": 5}, LOOP_EXHAUSTED),
        ({"demo_loop_count": 4}, "END"),
        ({}, "END"),
    ],
    ids=["count5", "count4", "unset"],
)
def test_after_demo_gate(state, expected):
    from langgraph.graph import END

    assert _after_demo(state) == (END if expected == "END" else expected)


# —— 图级回放：入口 demo 行 / 报错回传 / 计满断点 / docs_done 同轮接 demo ——


def test_graph_entry_demo_row_routes_error_back_into_demo_agent(tmp_path):
    model = ScriptedModel(["修复完成。", "第二次修复。"])
    app = build_graph(
        checkpointer=InMemorySaver(), model=model, workspace_root=tmp_path
    )
    cfg = _cfg("g-demo-1")
    seed = dict(DEMO_STATE)
    seed["actor_messages"] = [HumanMessage(content="主线")]
    seed["demo_messages"] = [HumanMessage(content="Traceback (most recent call last): boom")]
    r = app.invoke({**seed, "demo_loop_count": 0}, cfg)
    assert r["turn_end_reason"] == "round"
    assert model.calls[0]["role"] == "demo_agent"
    assert "报错上下文：Traceback (most recent call last): boom" in model.calls[0][
        "messages"
    ][0]["content"]

    r2 = app.invoke(
        {"demo_messages": [HumanMessage(content="第二次报错：Error: x")]}, cfg
    )
    assert r2["turn_end_reason"] == "round"
    assert len(model.calls) == 2
    assert "第二次报错：Error: x" in model.calls[1]["messages"][0]["content"]


def test_graph_docs_done_build_resolution_hands_to_demo_same_round(tmp_path):
    model = ScriptedModel(["写入：demo/main.py\nprint('hi')\n运行：python demo/main.py"])
    app = build_graph(
        checkpointer=InMemorySaver(), model=model, workspace_root=tmp_path
    )
    cfg = _cfg("g-demo-2")
    r0 = app.invoke(
        {
            "task_brief": "做个记账 CLI",
            "build_way": "way3",
            "todos": DONE_TODOS,
            "task_complete": True,
            "actor_messages": [HumanMessage(content="开始")],
        },
        cfg,
    )
    assert r0["turn_end_reason"] == "docs_done"
    r1 = app.invoke({"resolution_inputs": ["构建 demo"]}, cfg)
    assert r1["demo_phase"] == "building"
    assert r1["turn_end_reason"] == "round"  # demo 节点写断点（docs_done 不写）
    assert "运行权在用户（ADR-0003）" in r1["turn_end_payload"]["round_output"]
    assert (tmp_path / "demo" / "main.py").is_file()


def test_graph_demo_loop_count_5_hits_loop_exhausted_with_demo_scene(tmp_path):
    model = ScriptedModel(["不应被调用"])
    app = build_graph(
        checkpointer=InMemorySaver(), model=model, workspace_root=tmp_path
    )
    cfg = _cfg("g-demo-3")
    seed = dict(DEMO_STATE)
    seed["demo_loop_count"] = 4
    seed["demo_messages"] = [HumanMessage(content="第 4 次报错")]
    app.invoke(seed, cfg)  # 4 < 5：入口 demo 行 → demo 节点
    r = app.invoke(
        {"demo_messages": [HumanMessage(content="第 5 次报错")], "demo_loop_count": 5},
        cfg,
    )
    assert r["turn_end_reason"] == "loop_exhausted"
    assert "demo 环计数 5" in r["turn_end_payload"]["scene"]
