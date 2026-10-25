"""11 票切片 3：demo 轮压缩联动（验收 6，08 挂点第四处）。

DEMO_AGENT 节点包 with_compression（messages_key="demo_messages"）：
长 demo 历史 → 便宜模型被调、主模型收到头部单包；其它角色历史不越界。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from tests.doubles.fake_model import ScriptedModel

DONE_TODOS = [{"content": "写 README", "status": "completed"}]


def _cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def _history(n_rounds: int, chars: int) -> list:
    msgs: list = []
    for _ in range(n_rounds):
        msgs.append(HumanMessage(content="问"))
        msgs.append(AIMessage(content="字" * chars))
    return msgs


def _demo_seed() -> dict:
    """demo 构建中 + 长 demo 历史（8 轮 x 1000 字符，恰触发水线）。"""
    return {
        "task_brief": "想法",
        "build_way": "way1",
        "todos": DONE_TODOS,
        "task_complete": True,
        "demo_phase": "building",
        "demo_messages": _history(8, 1000),
    }


def _app(main, cheap, tmp_path: Path):
    return build_graph(
        checkpointer=InMemorySaver(),
        model=main,
        workspace_root=tmp_path,
        cheap_model=cheap,
    )


def test_demo_round_triggers_compression_hook(tmp_path):
    main = ScriptedModel(["demo 已生成。"])
    cheap = ScriptedModel(["demo 压缩摘要。"])
    app = _app(main, cheap, tmp_path)
    result = app.invoke(_demo_seed(), _cfg("demo-compress-1"))

    # 便宜模型先于 demo 主调用（role=compressor），prompt 含 demo 轮文本
    assert len(cheap.calls) == 1
    assert cheap.calls[0]["role"] == "compressor"
    assert "【R1】" in cheap.calls[0]["messages"][0]["content"]
    # 主模型是 demo_agent，且收到重排后历史（头部单包在前）
    assert main.calls[0]["role"] == "demo_agent"
    assert main.calls[0]["messages"][1]["content"].startswith("【R1-R5-compact】")
    # 压缩键合并进 state（持续）
    assert list(map(tuple, result.get("compacted_rounds") or [])) == [(1, 5)]
    assert result["turn_end_reason"] == "round"


def test_demo_compression_reads_demo_messages_not_actor_messages(tmp_path):
    """挂点读 demo 私有历史：actor_messages 再长也不触发 demo 轮压缩。"""
    main = ScriptedModel(["demo 已生成。"])
    cheap = ScriptedModel(["不应调用"])
    app = _app(main, cheap, tmp_path)
    seed = _demo_seed()
    seed["demo_messages"] = [HumanMessage(content="短历史")]
    seed["actor_messages"] = _history(8, 1000)
    app.invoke(seed, _cfg("demo-compress-2"))
    assert cheap.calls == []
    assert "compacted_rounds" not in app.get_state(_cfg("demo-compress-2")).values
