"""08 票切片 2：compress_rounds 便宜模型调用契约 + format_head_pack 头部单包形态 + find_error_conjectures。

验收 ②（头部单包+每包首行轮次目录）/④（便宜模型子档 role=compressor）/⑦ 错误猜想提取。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from project_agent.compression import (
    CompactionPack,
    compress_rounds,
    find_error_conjectures,
    format_head_pack,
    round_texts,
)
from tests.doubles.fake_model import ScriptedModel

# —— compress_rounds：便宜模型调用契约（验收 4 子档）——


def test_compress_rounds_calls_model_with_compressor_role():
    """便宜模型调用：role="compressor"（ModelClient.role 受控词汇新值）。"""
    model = ScriptedModel(["摘要文本"])
    text = compress_rounds(model, [(1, "轮一"), (2, "轮二")], thread_id="t-1")
    assert text == "摘要文本"
    assert len(model.calls) == 1
    assert model.calls[0]["role"] == "compressor"
    assert model.calls[0]["thread_id"] == "t-1"


def test_compress_rounds_prompt_contains_round_texts():
    """prompt 含每轮【R#】标记 + 轮文本 + 指令语。"""
    model = ScriptedModel(["摘要"])
    compress_rounds(model, [(1, "决定用浅色主题"), (5, "接口超时改 30 秒")], thread_id="t")
    prompt = model.calls[0]["messages"][0]["content"]
    assert "【R1】决定用浅色主题" in prompt
    assert "【R5】接口超时改 30 秒" in prompt
    assert "压缩以下构建轮次为摘要" in prompt


def test_compress_rounds_returns_model_text():
    model = ScriptedModel(["R1-R5 压缩摘要正文"])
    result = compress_rounds(model, [(1, "甲"), (2, "乙"), (3, "丙"), (4, "丁"), (5, "戊")], "th")
    assert result == "R1-R5 压缩摘要正文"


def test_compress_rounds_empty_rounds_still_calls_once():
    """空轮列表：仍按契约调用（prompt 只有指令行）——防御形态。"""
    model = ScriptedModel(["空摘要"])
    text = compress_rounds(model, [], thread_id="t")
    assert text == "空摘要"
    assert len(model.calls) == 1


# —— CompactionPack + format_head_pack：头部单包形态（验收 2）——


def test_format_head_pack_single_pack_shape():
    """单包形态：首行【R1-R5-compact】+ 摘要正文。"""
    pack = CompactionPack(
        covered_rounds=(1, 2, 3, 4, 5), summary="R1 决定 A；R3 改用 B。"
    )
    text = format_head_pack([pack])
    assert text == "【R1-R5-compact】\nR1 决定 A；R3 改用 B。"


def test_format_head_pack_multiple_packs_double_newline_separated():
    """多包合并：包间 \\n\\n 分隔，每包首行各自带覆盖轮次目录。"""
    packs = [
        CompactionPack(covered_rounds=(1, 2, 3, 4, 5), summary="甲摘要"),
        CompactionPack(covered_rounds=(6, 7), summary="乙摘要"),
    ]
    text = format_head_pack(packs)
    assert text == "【R1-R5-compact】\n甲摘要\n\n【R6-R7-compact】\n乙摘要"


def test_format_head_pack_empty_packs_returns_empty_string():
    assert format_head_pack([]) == ""


def test_compaction_pack_is_frozen():
    """CompactionPack 不可变（frozen dataclass）。"""
    pack = CompactionPack(covered_rounds=(1,), summary="s")
    try:
        pack.summary = "改"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("CompactionPack 应为 frozen")


# —— find_error_conjectures：错误猜想提取（验收 7 前半）——


def test_find_error_conjectures_keyword_lines():
    """行含"错误"/"失败"/"教训"关键词的行（strip 非空）入列表。"""
    summary = (
        "R1 决定用 SQLite。\n"
        "R2 遇到编码错误，教训是显式 utf-8。\n"
        "R3 接口失败两次后改用重试。\n"
        "R4 完成基础功能。\n"
        "\n"
        "  R5 优化了性能。  \n"
    )
    assert find_error_conjectures(summary) == [
        "R2 遇到编码错误，教训是显式 utf-8。",
        "R3 接口失败两次后改用重试。",
    ]


def test_find_error_conjectures_empty_summary():
    assert find_error_conjectures("") == []


def test_find_error_conjectures_no_keyword_lines():
    assert find_error_conjectures("全部成功。\n一切顺利。") == []


# —— round_texts 与消息形态互通（切片 2 收口）——


def test_round_texts_feeds_compress_rounds_pipeline():
    """round_texts 产出直接喂 compress_rounds（同一 (round_no, text) 形状）。"""
    messages = [
        HumanMessage(content="问1"),
        AIMessage(content="答1"),
        HumanMessage(content="问2"),
        AIMessage(content="答2"),
    ]
    rounds = round_texts(messages)
    model = ScriptedModel(["摘要"])
    compress_rounds(model, rounds, thread_id="t")
    prompt = model.calls[0]["messages"][0]["content"]
    assert "【R1】答1" in prompt and "【R2】答2" in prompt
