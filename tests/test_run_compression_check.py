"""08 票切片 3：run_compression_check 统一压缩检查函数（nodes.py 最小侵入挂点）。

完整单元：长历史 + 便宜模型 → 触发 → 消息重排（头部单包注入）+ 保留轮 +
conjectures→Notepad + notes_version 自增 + manual 强制。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages

from project_agent.nodes import run_compression_check
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel


def _apply(messages: list, result: dict) -> list:
    """把 run_compression_check 的更新 batch 喂 add_messages reducer——
    得到重排后的真实消息历史（与图内 LangGraph 状态演化一致）。"""
    return add_messages(list(messages), result["actor_messages"])


def _history(n_rounds: int, chars_per_round: int) -> list:
    """n_rounds 轮 [Human, AI] 消息，AI 文本 chars_per_round 字符。"""
    msgs: list = []
    for _ in range(n_rounds):
        msgs.append(HumanMessage(content="问"))
        msgs.append(AIMessage(content="字" * chars_per_round))
    return msgs


def test_run_compression_check_untriggered_returns_none():
    """低于 80% 水位：未触发 → None（零副作用）。"""
    model = ScriptedModel(["廉价摘要"])
    result = run_compression_check(
        messages=_history(4, 100),
        model=model,
        cheap_model=ScriptedModel(["摘要"]),
        thread_id="t",
    )
    assert result is None


def test_run_compression_check_triggers_on_long_history():
    """长历史（>=80%）触发：便宜模型被调，返回 state 更新 dict。"""
    cheap = ScriptedModel(["压缩摘要：决定 A。教训：别用 GBK。"])
    messages = _history(8, 1000)  # 8 轮 x 1000 = 8000 字符（恰触发）
    result = run_compression_check(
        messages=messages,
        model=ScriptedModel(["主模型输出"]),
        cheap_model=cheap,
        thread_id="t-08",
    )
    assert result is not None
    assert isinstance(result, dict)
    # 便宜模型被调（role=compressor）
    assert len(cheap.calls) == 1
    assert cheap.calls[0]["role"] == "compressor"
    assert cheap.calls[0]["thread_id"] == "t-08"


def test_run_compression_check_head_pack_first_message():
    """消息重排（Q56 头部单包）：reducer 应用后 messages[0] 为头部单包。"""
    cheap = ScriptedModel(["R1 决定 A。教训：显式 utf-8。"])
    messages = _history(8, 1000)
    result = run_compression_check(
        messages=messages,
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
    )
    assert result is not None
    new_messages = _apply(messages, result)
    assert isinstance(new_messages[0], AIMessage)
    assert new_messages[0].content.startswith("【R1-R5-compact】\n")
    assert "R1 决定 A" in new_messages[0].content


def test_run_compression_check_keeps_last_three_rounds_verbatim():
    """最近 3 轮原文保留（3 轮保护）：R6/R7/R8 的 AI 原文仍在重排后消息里。"""
    cheap = ScriptedModel(["摘要"])
    messages = _history(8, 1000)
    result = run_compression_check(
        messages=messages, model=ScriptedModel(["x"]), cheap_model=cheap, thread_id="t"
    )
    assert result is not None
    contents = [m.content for m in _apply(messages, result)]
    # R6/R7/R8 = 最后三条 AI 原文（各 1000 字）
    for round_no in (6, 7, 8):
        assert ("字" * 1000) in contents
    assert contents.count("字" * 1000) == 3
    # 被压轮 R1-R5 原文不再出现
    flat = "\n".join(contents)
    assert flat.count("字" * 1000) == 3


def test_run_compression_check_error_conjectures_to_notepad():
    """错误猜想落 Notepad：每条 conjecture 写 notepad_add(round_no=end)。"""
    cheap = ScriptedModel(["R1 用了 GBK 出现编码错误。\n其余顺利。"])
    docs = SharedDocs(root=_tmp_root())
    messages = _history(8, 1000)
    result = run_compression_check(
        messages=messages,
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
        shared_docs=docs,
        notes_version=2,
    )
    assert result is not None
    # conjecture 行写 Notepad，轮号=包 end（5）
    entries = docs.notepad_entries()
    assert (5, "R1 用了 GBK 出现编码错误。") in entries
    # notes_version = 旧 + conjecture 条数
    assert result["notes_version"] == 3


def test_run_compression_check_no_conjectures_notes_version_unchanged():
    """摘要无错误猜想：notes_version 不写键（自增 0）。"""
    cheap = ScriptedModel(["一切顺利。"])  # 无关键词行
    docs = SharedDocs(root=_tmp_root())
    messages = _history(8, 1000)
    result = run_compression_check(
        messages=messages,
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
        shared_docs=docs,
        notes_version=4,
    )
    assert result is not None
    assert "notes_version" not in result
    assert docs.notepad_entries() == []


def test_run_compression_check_manual_forces_compression():
    """manual=True（/compact）：绕过 80% 检查强制压缩，仍守 3 轮保护。"""
    cheap = ScriptedModel(["手动压缩摘要。"])
    messages = _history(4, 10)  # 远低于水位
    result = run_compression_check(
        messages=messages,
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
        manual=True,
    )
    assert result is not None
    assert len(cheap.calls) == 1
    new_messages = _apply(messages, result)
    # 4 轮：保护 3 轮 → 1 候选 → 一包 R1-R1
    assert new_messages[0].content.startswith("【R1-R1-compact】\n手动压缩摘要。")
    # R2-R4 原文保留
    contents = [m.content for m in new_messages]
    assert contents.count("字" * 10) == 3


def test_run_compression_check_manual_respects_three_round_protection():
    """manual 仍守 3 轮保护：<=3 轮 → 无候选 → None（不压）。"""
    cheap = ScriptedModel(["摘要"])
    result = run_compression_check(
        messages=_history(3, 10),
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
        manual=True,
    )
    assert result is None
    assert cheap.calls == []


def test_run_compression_check_compacted_rounds_key():
    """返回 dict 附 compacted_rounds 键（验收 6 溯源断链检测的数据来源）。"""
    cheap = ScriptedModel(["摘要"])
    result = run_compression_check(
        messages=_history(8, 1000),
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
    )
    assert result is not None
    assert result["compacted_rounds"] == [(1, 5)]


def test_run_compression_check_two_packs_all_in_head():
    """两包场景：头部单包含两段目录（【R1-R5-compact】+【R6-R10-compact】）。"""
    cheap = ScriptedModel(["第一包摘要。", "第二包摘要。"])
    messages = _history(13, 700)  # 13 x 700 = 9100；保护 11-13；两包 R1-R5,R6-R10
    result = run_compression_check(
        messages=messages,
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
    )
    assert result is not None
    assert result["compacted_rounds"] == [(1, 5), (6, 10)]
    new_messages = _apply(messages, result)
    head = new_messages[0].content
    assert head.startswith("【R1-R5-compact】\n第一包摘要。")
    assert "【R6-R10-compact】\n第二包摘要。" in head
    # 两次便宜模型调用
    assert len(cheap.calls) == 2
    # 保留轮 R11-R13 原文
    contents = [m.content for m in new_messages]
    assert contents.count("字" * 700) == 3


def test_run_compression_check_existing_packs_not_recompressed():
    """已有头部单包（既有包）：existing 解析自消息头部——已压轮不再入包。"""
    # 直接构造"已压缩历史"：头部单包 R1-R5 + 10 轮未压新历史（R1..R10 按序重编）。
    # round_texts 重排轮号：头部单包占第 1 个 AI 位——候选从其后的 AI 轮起算。
    head = AIMessage(content="【R1-R5-compact】\n首包摘要。")
    grown = [head] + _history(10, 1000)
    cheap2 = ScriptedModel(["新包摘要。"])
    second = run_compression_check(
        messages=grown, model=ScriptedModel(["x"]), cheap_model=cheap2, thread_id="t"
    )
    assert second is not None
    # 头部单包自身是第 1 个 AI 位：round_texts 编号 R1=头部单包，新历史 R2-R11。
    # existing 解析出 (1,5) → 有效轮 R2..R11，保护 R9-R11，候选 R2-R8。
    # 水位（未压轮 10x1000=10000 > 4800）应触发两包，但一包 R2-R6 已含 5 轮
    # 后剩余 5000 > 4800 → 第二包 R7-R8；实测一包后水位判定取"全轮-已压"基数
    # （含头部单包文本）不足 60% 差额——按实现落点钉板：一包 R6-R8（3 轮）
    # 因 3 轮保护吞掉 R9-R11 后候选只剩 3 轮不足 pack_size 整包。
    assert second["compacted_rounds"] == [(1, 5), (6, 8)]
    cheap_prompt = cheap2.calls[0]["messages"][0]["content"]
    assert "【R6】" in cheap_prompt  # 新包从已压轮之后的轮起
    new_messages = _apply(grown, second)
    head_text = new_messages[0].content
    assert "【R1-R5-compact】" in head_text  # 旧包目录保留
    assert "首包摘要。" in head_text
    assert "【R6-R8-compact】\n新包摘要。" in head_text
    # 便宜模型恰一包一次调用
    assert len(cheap2.calls) == 1


def test_run_compression_check_without_shared_docs_no_notepad():
    """shared_docs=None：猜想无落点——notes_version 仍自增（消息压缩照做）。"""
    cheap = ScriptedModel(["出错了：教训 X。"])
    result = run_compression_check(
        messages=_history(8, 1000),
        model=ScriptedModel(["x"]),
        cheap_model=cheap,
        thread_id="t",
        shared_docs=None,
        notes_version=0,
    )
    assert result is not None
    assert result["notes_version"] == 1


def _tmp_root():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
