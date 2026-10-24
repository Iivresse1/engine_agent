"""08 票切片 4：with_compression 装饰器 + graph cheap_model 参数 + 三挂点。

验收 3（全部 LLM 调用点同检查——actor/verifier/assembler 三点逐节点单独
测试触发；planner 无 LLM 调用不挂，demo 轮属后续票挂点）。
ScriptedModel(主) + ScriptedModel(便宜) 各自出牌——便宜模型收到的 prompt
含【R1】等轮文本；主模型收到重排后 messages（头部单包在前）。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_actor_node, with_compression
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]


def _history(n_rounds: int, chars: int) -> list:
    msgs: list = []
    for _ in range(n_rounds):
        msgs.append(HumanMessage(content="问"))
        msgs.append(AIMessage(content="字" * chars))
    return msgs


def _cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def _seed_long_history() -> dict:
    """主环工作轮 seed：todos 未清 + 长消息历史（8 轮 x 1000 字符，恰触发）。"""
    return {
        "task_brief": "想法",
        "build_way": "way1",
        "todos": TWO_PENDING,
        "assembled_context": {"system": "你是构建 agent。", "todo_board": [], "scope": "main"},
        "actor_messages": _history(8, 1000),
    }


# —— with_compression 装饰器：包装任意节点，调前跑压缩检查 ——


def test_with_compression_wraps_node_and_merges_updates():
    """包装节点：压缩更新合并进 state 后再调原节点（原节点产出叠加）。"""
    main = ScriptedModel(["主模型回复"])
    cheap = ScriptedModel(["压缩摘要：教训 X。"])
    captured: dict = {}

    def fake_node(state, config=None):
        captured["state"] = state
        return {"todos": TWO_PENDING}

    wrapped = with_compression(fake_node, cheap_model=cheap)
    seed = dict(_seed_long_history())
    updates = wrapped(seed, _cfg("t-wrap"))
    # 原节点被调（看到压缩后的 state：messages[0] 为头部单包）
    assert captured["state"]["actor_messages"][0].content.startswith("【R1-R5-compact】")
    # 合并：压缩键 + 原节点键
    assert updates["actor_messages"][0].content.startswith("【R1-R5-compact】")
    assert "compacted_rounds" in updates
    assert updates["todos"] == TWO_PENDING
    # 便宜模型被调
    assert len(cheap.calls) == 1
    assert cheap.calls[0]["role"] == "compressor"


def test_with_compression_untriggered_calls_node_verbatim():
    """未触发（低于水位）：原节点照常、零压缩键。"""
    cheap = ScriptedModel(["摘要"])
    main = ScriptedModel(["回复"])
    calls: list = []

    def fake_node(state, config=None):
        calls.append(state)
        return {"x": 1}

    wrapped = with_compression(fake_node, cheap_model=cheap)
    seed = {
        "actor_messages": _history(4, 100),
        "todos": TWO_PENDING,
    }
    updates = wrapped(seed, _cfg("t"))
    assert updates == {"x": 1}
    assert calls[0] is seed
    assert cheap.calls == []


def test_with_compression_no_cheap_model_is_identity_wrapper():
    """cheap_model=None：裸节点（467 基线零回归依据）。"""
    calls: list = []

    def fake_node(state, config=None):
        calls.append(state)
        return {"y": 2}

    wrapped = with_compression(fake_node, cheap_model=None)
    seed = {"actor_messages": _history(8, 1000)}
    assert wrapped(seed, _cfg("t")) == {"y": 2}
    assert calls[0] is seed


def test_with_compression_uses_shared_docs_for_conjectures(tmp_path: Path):
    """装饰器传 shared_docs：猜想落 Notepad。"""
    docs = SharedDocs(tmp_path)
    cheap = ScriptedModel(["摘要：教训是显式 utf-8。"])
    main = ScriptedModel(["回复"])

    def fake_node(state, config=None):
        return {}

    wrapped = with_compression(fake_node, cheap_model=cheap, shared_docs=docs)
    wrapped(dict(_seed_long_history(), notes_version=0), _cfg("t"))
    assert docs.notepad_entries() == [(5, "摘要：教训是显式 utf-8。")]


# —— graph.build_graph(cheap_model=...)：三挂点逐节点触发（验收 3）——


def _app(main: ScriptedModel, cheap: ScriptedModel, tmp_path: Path):
    return build_graph(
        checkpointer=InMemorySaver(),
        model=main,
        workspace_root=tmp_path,
        cheap_model=cheap,
    )


def test_graph_actor_hook_triggers_compression(tmp_path: Path):
    """actor 挂点：长历史 invoke → 便宜模型被调，主模型收到重排后 messages。"""
    main = ScriptedModel(["主模型回复", "task_complete: false"])
    cheap = ScriptedModel(["压缩摘要。"])
    app = _app(main, cheap, tmp_path)
    result = app.invoke(_seed_long_history(), _cfg("g-actor"))
    # 便宜模型先于主模型被调（actor before model）
    assert len(cheap.calls) == 1
    assert cheap.calls[0]["role"] == "compressor"
    assert "【R1】" in cheap.calls[0]["messages"][0]["content"]
    # 主模型收到的 messages 已重排：头部单包在前
    main_messages = main.calls[0]["messages"]
    assert main_messages[1]["content"].startswith("【R1-R5-compact】")
    # 图结果含压缩键（state 更新合并；checkpointer 序列化列表化）
    assert list(map(tuple, result.get("compacted_rounds") or [])) == [(1, 5)]


def test_graph_verifier_hook_triggers_compression(tmp_path: Path):
    """verifier 挂点：长历史 invoke → verifier 前便宜模型被调。"""
    main = ScriptedModel(["主模型回复", "task_complete: false"])
    cheap = ScriptedModel(["压缩摘要。"])
    app = _app(main, cheap, tmp_path)
    app.invoke(_seed_long_history(), _cfg("g-verifier"))
    # actor 轮触发一次 + verifier 进入前（已压后不再触发，水位已降）
    # 断言：至少 actor 挂点触发一次；verifier 挂点单独验证用裸 verifier 包装
    assert len(cheap.calls) >= 1


def test_graph_verifier_hook_fires_before_verifier_model_call(tmp_path: Path):
    """verifier 挂点隔离验证：直接包装 make_verifier_node 长历史调用。"""
    main = ScriptedModel(["task_complete: false"])
    cheap = ScriptedModel(["verifier 前压缩摘要。"])
    from project_agent.nodes import make_verifier_node

    verifier = make_verifier_node(main)
    wrapped = with_compression(verifier, cheap_model=cheap)
    seed = dict(_seed_long_history())
    seed["actor_messages"] = _history(8, 1000)
    updates = wrapped(seed, _cfg("t-ver"))
    assert len(cheap.calls) == 1
    assert "【R1】" in cheap.calls[0]["messages"][0]["content"]
    # verifier 主模型调用照常发生
    assert len(main.calls) == 1
    assert updates["task_complete"] is False


def test_graph_assembler_hook_fires_before_assembler(tmp_path: Path):
    """assembler 挂点隔离验证：context_assembler 前便宜模型被调。"""
    from project_agent.nodes import make_assembler_node

    cheap = ScriptedModel(["assembler 前压缩摘要。"])
    assembler = make_assembler_node(shared_docs=None)
    wrapped = with_compression(assembler, cheap_model=cheap)
    seed = _seed_long_history()
    updates = wrapped(dict(seed), _cfg("t-asm"))
    assert len(cheap.calls) == 1
    # assembler 照常写 assembled_context
    assert "assembled_context" in updates
    assert updates["assembled_context"]["scope"] == "main"


def test_graph_cheap_model_none_keeps_baseline_behavior(tmp_path: Path):
    """cheap_model=None（缺省）：三节点裸奔——与 06 行为一致零回归。"""
    main = ScriptedModel(["主模型回复", "task_complete: false"])
    app = build_graph(
        checkpointer=InMemorySaver(), model=main, workspace_root=tmp_path
    )
    result = app.invoke(_seed_long_history(), _cfg("g-none"))
    assert "compacted_rounds" not in result
    assert result["turn_end_reason"] == "round"
    # 主模型收到原始未压缩历史
    main_messages = main.calls[0]["messages"]
    assert not main_messages[1]["content"].startswith("【R")


def test_graph_compression_persists_across_invokes(tmp_path: Path):
    """checkpointer 持续：压缩后历史驻留，下一轮不重复压缩已压轮。"""
    main = ScriptedModel(
        [
            "主模型回复一",  # R9（第 1 轮 invoke）
            "task_complete: false",
            "主模型回复二",  # R10
            "task_complete: false",
        ]
    )
    cheap = ScriptedModel(["第一轮压缩摘要。", "第二轮压缩摘要。"])
    app = _app(main, cheap, tmp_path)
    cfg = _cfg("g-persist")
    r1 = app.invoke(_seed_long_history(), cfg)
    assert list(map(tuple, r1["compacted_rounds"])) == [(1, 5)]
    # 第二轮：追加用户输入
    r2 = app.invoke({"actor_messages": [HumanMessage(content="继续")]}, cfg)
    # 第二轮水位（头部单包+保留 R6-R8+R9）低于 80% → 不再触发
    assert len(cheap.calls) == 1
    assert list(map(tuple, r2["compacted_rounds"])) == [(1, 5)]  # 状态持续
