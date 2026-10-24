"""08 票切片 1：压缩纯函数——round_texts / should_compress / plan_packs 四条边界表驱动。

验收 1：80% 触发 / 3 轮保护 / 水位 60%（两包上限）/ pack 边界——全部表驱动。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from project_agent.compression import plan_packs, round_texts, should_compress


def _rounds(n: int, chars_per_round: int = 10) -> list[tuple[int, str]]:
    """n 轮假历史：轮号 1..n，每轮文本 chars_per_round 个字符。"""
    return [(i, "字" * chars_per_round) for i in range(1, n + 1)]


def _messages(n: int, ai_chars: int = 10, human_chars: int = 0) -> list:
    """n 轮消息形态：[Human, AI] * n——round_texts 的标准输入。

    human_chars=0 时 HumanMessage 空文本（不贡献估算，round_texts 仍正常配对）。
    """
    msgs: list = []
    for _ in range(n):
        msgs.append(HumanMessage(content="问" * human_chars))
        msgs.append(AIMessage(content="字" * ai_chars))
    return msgs


def _msgs_with_total(total_chars: int) -> list:
    """总字符恰为 total_chars 的消息对（AI 全额 + Human 空）。"""
    return _messages(1, ai_chars=total_chars, human_chars=0)


# —— round_texts：AIMessage 序号即轮次，HumanMessage 配对同轮 ——


def test_round_texts_pairs_human_ai_by_ai_order():
    msgs = [
        HumanMessage(content="问1"),
        AIMessage(content="答1"),
        HumanMessage(content="问2"),
        AIMessage(content="答2"),
        HumanMessage(content="问3"),
        AIMessage(content="答3"),
    ]
    assert round_texts(msgs) == [(1, "答1"), (2, "答2"), (3, "答3")]


def test_round_texts_consecutive_ai_messages_each_own_round():
    """连续 AIMessage（无 Human 配对）各占一轮——按序号 1..n。"""
    msgs = [AIMessage(content="甲"), AIMessage(content="乙"), AIMessage(content="丙")]
    assert round_texts(msgs) == [(1, "甲"), (2, "乙"), (3, "丙")]


def test_round_texts_leading_human_counts_before_first_round():
    msgs = [HumanMessage(content="开场"), AIMessage(content="答1")]
    assert round_texts(msgs) == [(1, "答1")]


def test_round_texts_empty_returns_empty():
    assert round_texts([]) == []


def test_round_texts_ignores_non_string_content():
    """content 非字符串（防御）：跳过该消息不计数。"""
    from langchain_core.messages import AIMessage as AI

    msg = AI(content=["chunk"])  # list content（多模态形态）
    assert round_texts([msg]) == []


# —— should_compress：字符数近似 tokens，占比 >= 0.80 触发 ——


@pytest.mark.parametrize(
    ("total_chars", "budget", "expected"),
    [
        (6399, 8000, False),  # 0.799875 —— 80% 以下不触发
        (6400, 8000, True),  # 恰 80% 触发（>=）
        (6399, 8000, False),  # 80% 以下（重复钉边界）
        (6401, 8000, True),  # 超 80% 触发
        (0, 8000, False),  # 空
    ],
    ids=["below-80", "exactly-80", "below-80-again", "above-80", "empty"],
)
def test_should_compress_threshold_table(total_chars, budget, expected):
    msgs = _msgs_with_total(total_chars)
    assert should_compress(msgs, budget_tokens=budget) is expected


def test_should_compress_counts_all_message_text():
    """估算 = 全部消息文本 len 之和（Human+AI 都算）。"""
    msgs = [
        HumanMessage(content="甲" * 1000),
        AIMessage(content="乙" * 1000),
    ]
    # 总 2000，budget 2500 → 0.8 → 触发
    assert should_compress(msgs, budget_tokens=2500) is True


def test_should_compress_default_budget_8000():
    """默认 budget=8000：6399 不触 / 6400 触（80% = 6400 字符）。"""
    assert should_compress(_msgs_with_total(6399)) is False
    assert should_compress(_msgs_with_total(6400)) is True


# —— plan_packs：3 轮保护 / pack_size=5 / 水位 60% / 两包上限 / existing 排除 ——


def test_plan_packs_three_round_protection():
    """3 轮保护：总数 <= keep_last → 无候选 → []。"""
    assert plan_packs(_rounds(3)) == []


def test_plan_packs_four_rounds_single_small_pack():
    """4 轮（保护后 1 候选）：一包 R1-R1。"""
    assert plan_packs(_rounds(4)) == [(1, 1)]


def test_plan_packs_ten_rounds_two_packs():
    """10 轮各 800 字（总量 8000）：保护后候选 R1..R7——一包 R1-R5 压掉 4000，
    剩 4000 <= 水位 4800 → 停（单包）。"""
    rounds = _rounds(10, chars_per_round=800)
    assert plan_packs(rounds) == [(1, 5)]


def test_plan_packs_two_packs_when_waterline_not_reached():
    """水位不足再压一包：总量足够大时两包都压仍超水位，但上限 2 包。"""
    # 25 轮各 400 字：总量 10000；一包 R1-R5 → 剩 8000 > 4800 → 第二包 R6-R10
    # → 剩 6000 仍 > 4800，两包上限停止。
    rounds = _rounds(25, chars_per_round=400)
    assert plan_packs(rounds) == [(1, 5), (6, 10)]


def test_plan_packs_empty_no_candidates():
    assert plan_packs([]) == []


def test_plan_packs_respects_max_packs():
    """两包上限：一包远不够降水位的历史——最多 2 包（与两包水位测试互补钉板）。"""
    # 25 轮各 400 字：总量 10000；保护后 22 候选。一包 2000 → 剩 8000 > 4800；
    # 第二包 → 剩 6000 仍 > 4800；上限停。
    rounds = _rounds(25, chars_per_round=400)
    packs = plan_packs(rounds)
    assert len(packs) == 2  # 上限钉板：绝不多于 2
    assert packs[0] == (1, 5)  # 从最老起第一包


def test_plan_packs_waterline_stops_after_one_pack():
    """水位 60%：一包后估算 <= 0.60*budget → 不加第二包。"""
    # 8 轮各 1000 字：总量 8000 恰触发；保护后 5 候选 → 一包 R1-R5 压掉 5000，
    # 剩 3000 <= 4800 → 停。
    rounds = _rounds(8, chars_per_round=1000)
    assert plan_packs(rounds) == [(1, 5)]


def test_plan_packs_existing_overlaps_excluded():
    """已压区间重叠轮排除：R1-R5 已压 → 候选从 R6 起（R10-12 保护）。"""
    rounds = _rounds(12, chars_per_round=1000)
    packs = plan_packs(rounds, existing=[(1, 5)])
    assert packs == [(6, 9)]


def test_plan_packs_existing_keeps_head_pack_semantics():
    """existing 覆盖头部（R1-R10 已压）：候选 R11..R17，两包后仍超水位
    ——上限 2 包（(11,15)+(16,17)）。"""
    rounds = _rounds(20, chars_per_round=600)
    packs = plan_packs(rounds, existing=[(1, 10)])
    assert packs == [(11, 15), (16, 17)]


def test_plan_packs_all_rounds_existing_returns_empty():
    rounds = _rounds(6, chars_per_round=1000)
    assert plan_packs(rounds, existing=[(1, 6)]) == []


def test_plan_packs_waterline_counts_existing_compressed_text():
    """水位计算含 existing 已压区间（已压轮仍占消息头部单包体积，按轮文本估算）。"""
    # 15 轮各 1000：已压 R1-R5（头部单包 5000 仍在消息里），新候选 R6-R12。
    # 一包 R6-R10 → 头部 10000 + 保留 3000 = 13000 > 60%*8000=4800 → 再一包
    # R11-R12 → 13000。两包上限。
    rounds = _rounds(15, chars_per_round=1000)
    packs = plan_packs(rounds, existing=[(1, 5)])
    assert packs == [(6, 10), (11, 12)]


def test_plan_packs_partial_existing_overlap_splits_candidates():
    """existing 区间部分覆盖候选包：重叠轮排除后按剩余轮从最老起打包。"""
    # 12 轮各 1000：existing=(2,3) → 候选 1,4,5,6,7,8,9（保护后 R1..R9 减去 2,3）。
    rounds = _rounds(12, chars_per_round=1000)
    packs = plan_packs(rounds, existing=[(2, 3)])
    # 候选轮 [1,4,5,6,7,8,9]：第一包 5 轮 [1,4,5,6,7] → (1,7)；剩 [8,9] 第二包
    # 水位：压后 7000 > 4800 → 第二包 (8,9)。
    assert packs == [(1, 7), (8, 9)]
