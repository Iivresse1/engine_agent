"""distill_round 纯函数 + round_summary 写入（05 票终裁 8，验收 4）+ cli TODO 注释。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from project_agent.nodes import distill_round, make_actor_node
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]


def _assembled() -> dict:
    return {"system": "你是构建 agent。", "todo_board": [], "scope": "main"}


def test_distill_round_takes_last_ai_message_head_120_chars():
    text = "字" * 200
    assert distill_round([HumanMessage(content="问"), AIMessage(content=text)]) == "字" * 120


def test_distill_round_short_content_kept_whole():
    messages = [AIMessage(content="短回复")]
    assert distill_round(messages) == "短回复"


def test_distill_round_empty_messages_returns_empty_string():
    assert distill_round([]) == ""


def test_distill_round_human_only_returns_empty_string():
    assert distill_round([HumanMessage(content="只有人类消息")]) == ""


def test_distill_round_picks_the_last_ai_message():
    messages = [
        HumanMessage(content="问1"),
        AIMessage(content="旧回复"),
        HumanMessage(content="问2"),
        AIMessage(content="新回复"),
    ]
    assert distill_round(messages) == "新回复"


def test_actor_writes_round_summary_at_end():
    """actor 末尾显式调用 distill_round 写 round_summary（Q53=b）。"""
    model = ScriptedModel(["完成：梳理需求边界。模型长回复正文。"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(),
        "actor_messages": [HumanMessage(content="开始")],
    }
    updates = node(state, {"configurable": {"thread_id": "ts-1"}})
    assert updates["round_summary"] == "完成：梳理需求边界。模型长回复正文。"


def test_actor_model_none_no_round_summary():
    """model=None 无 AIMessage：不写 round_summary（无产出可提炼）。"""
    node = make_actor_node(None)
    updates = node({"todos": TWO_PENDING, "assembled_context": _assembled()}, {})
    assert "round_summary" not in updates


def test_cli_carries_metered_model_todo_comment():
    """v1.5 接线票：TODO 哨兵退役——真接线落地（MeteredModel 经
    build_model_runtime 装配，build_graph 带 model/cheap_model/workspace_root）。"""
    from pathlib import Path

    cli_src = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "project_agent"
        / "cli.py"
    ).read_text(encoding="utf-8")
    assert "build_model_runtime" in cli_src
    assert "model=runtime.model" in cli_src
    assert "cheap_model=runtime.cheap_model" in cli_src
    assert "workspace_root=Path.cwd()" in cli_src
    assert "TODO" not in cli_src  # 骨架期欠账注释清账
