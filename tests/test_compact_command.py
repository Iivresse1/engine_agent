"""08 票切片 5：/compact 手动兜底（repl 最小）+ 溯源断链检测（验收 6）。

/compact → run_compression_check(manual=True)；ReplHost 构造加可选
cheap_model/shared_docs 参数（默认 None 不启用，既有测试零改动）；
无依赖时打印"压缩未启用（需 --cheap-model 接线）"。

断链检测：压缩后 SharedDocs.read_round(r) 仍可检索被压轮【R#】原文——
磁盘是事实来源（ADR-0004），消息历史压缩不破坏磁盘溯源——
磁盘条目数 >= 消息历史轮数 - 已压轮数。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import run_compression_check
from project_agent.repl import ReplHost
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel
from tests.doubles.scripted_io import ScriptedIO


def _history(n_rounds: int, chars: int) -> list:
    msgs: list = []
    for _ in range(n_rounds):
        msgs.append(HumanMessage(content="问"))
        msgs.append(AIMessage(content="字" * chars))
    return msgs


def _cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


# —— /compact：REPL 斜杠命令 ——


class _StubApp:
    """REPL 测试桩：invoke 返回断点协议最小 round 形状。

    模拟真实图行为：update 键（含压缩批的 compacted_rounds）并入结果 state——
    真实 LangGraph 会持久化节点 update 的全部 state 键。
    """

    def __init__(self) -> None:
        self.invocations = 0
        self.last_update: dict = {}

    def invoke(self, update, config):
        self.invocations += 1
        self.last_update = update
        state = {
            "turn_end_reason": "round",
            "turn_end_payload": {"round_output": "ok", "todo_board": []},
        }
        for key, value in update.items():
            if key != "actor_messages":  # 消息批经 reducer 归约——桩不模拟
                state[key] = value
        return state


def _seeded_history() -> list:
    """8 轮 x 1000 字符长历史（/compact 手动场景）。"""
    return _history(8, 1000)


def test_repl_compact_runs_manual_compression(workspace):
    """/compact：调 run_compression_check(manual=True)——消息被压缩。"""
    cheap = ScriptedModel(["手动压缩摘要。"])
    docs = SharedDocs(workspace.root)
    app = _StubApp()
    io = ScriptedIO(["/compact", "/exit"])
    host = ReplHost(app, io, "t-compact", cheap_model=cheap, shared_docs=docs)
    # 预置长历史进 _last_state（REPL 持有断点状态）
    host._last_state = {
        "actor_messages": _seeded_history(),
        "notes_version": 0,
    }
    host.run()
    # 便宜模型被调（manual 压缩）
    assert len(cheap.calls) == 1
    assert cheap.calls[0]["role"] == "compressor"
    out = "\n".join(io.outputs)
    assert "压缩" in out  # 压缩结果通告


def test_repl_compact_without_deps_prints_notice(workspace):
    """/compact 无依赖（cheap_model=None）：打印"压缩未启用（需 --cheap-model 接线）"。"""
    app = _StubApp()
    io = ScriptedIO(["/compact", "/exit"])
    host = ReplHost(app, io, "t-notice")
    host._last_state = {"actor_messages": _seeded_history()}
    host.run()
    out = "\n".join(io.outputs)
    assert "压缩未启用（需 --cheap-model 接线）" in out
    assert app.invocations == 0  # 不进主图


def test_repl_compact_help_lists_command(workspace):
    """/help 命令表含 /compact。"""
    io = ScriptedIO(["/help", "/exit"])
    ReplHost(_StubApp(), io, "t-help").run()
    out = "\n".join(io.outputs)
    assert "/compact" in out


def test_repl_compact_short_history_still_protects(workspace):
    """/compact 守 3 轮保护：<=3 轮无候选 → 通告"无可压缩轮次"。"""
    cheap = ScriptedModel(["摘要"])
    docs = SharedDocs(workspace.root)
    io = ScriptedIO(["/compact", "/exit"])
    host = ReplHost(_StubApp(), io, "t-short", cheap_model=cheap, shared_docs=docs)
    host._last_state = {"actor_messages": _history(3, 10), "notes_version": 0}
    host.run()
    assert cheap.calls == []  # 3 轮保护：便宜模型零调用
    out = "\n".join(io.outputs)
    assert "无可压缩轮次" in out


def test_repl_compact_updates_last_state_messages(workspace):
    """/compact 后 REPL 持有的消息历史即重排结果（下轮 invoke 携带）。"""
    cheap = ScriptedModel(["手动摘要。"])
    docs = SharedDocs(workspace.root)
    app = _StubApp()
    io = ScriptedIO(["/compact", "继续", "/exit"])
    host = ReplHost(app, io, "t-state", cheap_model=cheap, shared_docs=docs)
    host._last_state = {"actor_messages": _seeded_history(), "notes_version": 0}
    host.run()
    # /compact 后 "继续" 走 _run_turn → fusion_update 产出新 HumanMessage，
    # 与压缩批（RemoveMessage+头部单包）一起进 update["actor_messages"]：
    # 批内含头部单包 AIMessage（id 复用首条）——在批序列里验证。
    msgs = app.last_update["actor_messages"]
    head_candidates = [
        m for m in msgs
        if isinstance(m, AIMessage)
        and isinstance(m.content, str)
        and m.content.startswith("【R1-R5-compact】")
    ]
    assert head_candidates, "invoke update 应携带压缩头部单包"
    # REPL 持有状态本身也携带压缩键（StubApp 返回不含该键——用 /compact 更新验证）
    cheap_again = ScriptedModel(["再压。"])
    host._cheap_model = cheap_again
    host._compact()
    assert host._last_state.get("compacted_rounds") is not None


# —— 验收 6：溯源断链检测 ——


def test_read_round_retrieves_compacted_rounds_after_graph_compression(tmp_path: Path):
    """图级完整链：长历史 → 压缩 → SharedDocs.read_round(r) 仍检索被压轮原文。

    磁盘是事实来源（ADR-0004）：消息历史压缩不破坏磁盘溯源。
    断链检测 = 磁盘条目数 >= 消息历史轮数 - 已压轮数。
    """
    # 造 12 轮磁盘历史（模拟既有 BUILD_LOG）
    docs = SharedDocs(tmp_path)
    for round_no in range(1, 13):
        docs.append_round_entry(round_no, f"第 {round_no} 轮内容原文")
    # 消息历史与磁盘对齐（12 轮 AI 消息）
    messages = _history(12, 1000)

    result = run_compression_check(
        messages=messages,
        model=None,
        cheap_model=ScriptedModel(["摘要。", "摘要二。"]),
        thread_id="t-prov",
        shared_docs=docs,
    )
    assert result is not None
    compacted = result["compacted_rounds"]
    # 12 轮 x 1000：候选 R1-R9（保护 R10-R12），一包 R1-R5 后剩 7000 > 4800
    # → 第二包 R6-R9 → 停（两包或水位达）。8 轮 AI 起头是 Human("问")，
    # 12 轮历史里首条消息为 Human——头部单包覆写该位。
    assert list(map(tuple, compacted)) == [(1, 5), (6, 9)]

    # 断链检测：磁盘条目数（12）>= 消息历史轮数（12）- 已压轮数（10）
    disk_rounds = docs.read_rounds()
    assert len(disk_rounds) == 12
    n_compacted = sum(end - start + 1 for start, end in compacted)
    assert len(disk_rounds) >= 12 - n_compacted

    # 被压轮原文仍可经【R#】检索（磁盘事实来源不随消息压缩丢失）
    for round_no in (1, 5, 6, 9):
        assert docs.read_round(round_no) == f"【R{round_no}】第 {round_no} 轮内容原文"


def test_graph_level_provenance_survives_compression(tmp_path: Path):
    """图级：多轮 invoke 自然积累磁盘历史 → 触发压缩 → read_round 全程可检索。"""
    main = ScriptedModel(
        [
            "主模型回复一",
            "task_complete: false",
            "主模型回复二",
            "task_complete: false",
        ]
    )
    cheap = ScriptedModel(["压缩摘要。"])
    # 预置磁盘 10 轮 + 长消息历史（图级触发）
    docs = SharedDocs(tmp_path)
    for round_no in range(1, 11):
        docs.append_round_entry(round_no, f"磁盘第 {round_no} 轮")
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=main, workspace_root=tmp_path, cheap_model=cheap)
    seed = {
        "task_brief": "想法",
        "build_way": "way1",
        "todos": [{"content": "梳理需求边界", "status": "pending"}],
        "assembled_context": {"system": "你是构建 agent。", "todo_board": [], "scope": "main"},
        "actor_messages": _history(10, 900),
    }
    r1 = app.invoke(seed, _cfg("g-prov"))
    compacted = list(map(tuple, r1.get("compacted_rounds") or []))
    # 10x900=9000 > 6400 触发：候选 R1-R7（保护 R8-R10），一包 R1-R5 后
    # remaining 4500 <= 水位 4800 → 停（单包）。
    assert compacted == [(1, 5)]
    # 磁盘 10 轮全程可检索（压缩不动磁盘）
    for round_no in range(1, 11):
        assert docs.read_round(round_no) == f"【R{round_no}】磁盘第 {round_no} 轮"
    # 断链检测不等式成立
    n_compacted = sum(end - start + 1 for start, end in compacted)
    disk_rounds = docs.read_rounds()
    assert len(disk_rounds) >= 10 - n_compacted
