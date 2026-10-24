"""08 票：上下文压缩（Q50/Q54/Q56 终裁）。

Q50：80% 阈值触发 → 便宜模型压最老 n 轮（n=5/包）入【R#-compact】摘要；
压后水位目标 <=60%（不足再压一包，同轮最多两包）；最近 3 轮原文永不压缩；
压缩中发现的错误猜想写 Notepad。
Q54：压缩检查 = 模型调用前统一检查（挂点见 nodes.with_compression）。
Q56：压缩包注入 = 头部单包——全部【R#-compact】摘要合并为消息历史头部
单一记忆区，每包首行"【R{start}-R{end}-compact】"标注覆盖轮次。

token 估算：sum(len(text)) 字符数近似（Q50 终裁的轻量水位计）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from langchain_core.messages import AIMessage

from project_agent.model_client import ModelClient

# Q50 终裁常量：80% 触发 / 60% 水位目标 / 包大小 5 / 最近 3 轮保护 / 最多两包
DEFAULT_BUDGET_TOKENS = 8000
TRIGGER_RATIO = 0.80
WATERLINE_RATIO = 0.60
DEFAULT_PACK_SIZE = 5
DEFAULT_KEEP_LAST = 3
DEFAULT_MAX_PACKS = 2

# 压缩角色（ModelClient.role 受控词汇新值——便宜模型子档调用记账）
COMPRESSOR_ROLE = "compressor"

# 头部单包每包首行目录标记：【R{start}-R{end}-compact】（Q56）
_COMPACT_HEADER_RE = re.compile(r"【R(\d+)-R(\d+)-compact】")


@dataclass(frozen=True)
class CompactionPack:
    """一个压缩包：覆盖轮次（含端点）+ 便宜模型产出的摘要文本。"""

    covered_rounds: tuple[int, ...]  # 覆盖轮次（如 (1,2,3,4,5)=R1..R5）
    summary: str  # 便宜模型产出的摘要文本


def round_texts(messages: Any) -> list[tuple[int, str]]:
    """actor_messages → [(round_no, text)]：每条 AIMessage=一轮产出。

    实现：顺序扫，遇 AIMessage 即轮次 +1 取该消息文本（HumanMessage 为用户
    输入配对在同一轮，不单独计数）。content 非字符串的消息跳过。
    """
    rounds: list[tuple[int, str]] = []
    round_no = 0
    for msg in messages or []:
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                round_no += 1
                rounds.append((round_no, content))
    return rounds


def estimate_tokens(messages: Any) -> int:
    """估算 tokens = sum(len(text))（全部消息字符数近似）。"""
    total = 0
    for msg in messages or []:
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            total += len(content)
    return total


def should_compress(
    messages: Any, *, budget_tokens: int = DEFAULT_BUDGET_TOKENS
) -> bool:
    """80% 阈值水位检查：估算 / budget >= 0.80 → True。"""
    if budget_tokens <= 0:
        return True
    return estimate_tokens(messages) / budget_tokens >= TRIGGER_RATIO


def plan_packs(
    rounds: list[tuple[int, str]],
    *,
    pack_size: int = DEFAULT_PACK_SIZE,
    keep_last: int = DEFAULT_KEEP_LAST,
    max_packs: int = DEFAULT_MAX_PACKS,
    existing: Sequence[tuple[int, int]] = (),
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> list[tuple[int, int]]:
    """返回 [(start, end)] 待压轮区间列表（含端点，按轮号升序）。

    1) 候选 = 除最近 keep_last 轮外、且不在 existing 已压区间内的全部轮，
       按轮号升序
    2) 从最老起每 pack_size 轮一包；水位目标：压后剩余估算 <= 0.60*budget
       —— 不足（仍 >60%）再压一包（同批最多 max_packs 包）
    3) 不足一轮 / 无候选 → []
    """
    if not rounds:
        return []
    ordered = sorted(rounds, key=lambda item: item[0])
    # 3 轮保护：最近 keep_last 轮永不压缩
    protected = {no for no, _ in ordered[-keep_last:]} if keep_last > 0 else set()
    # 与已压缩区间重叠的轮排除（已压轮驻留头部单包，不再入包）
    compressed = {no for start, end in existing for no in range(start, end + 1)}
    candidates = [item for item in ordered if item[0] not in protected and item[0] not in compressed]
    if not candidates:
        return []

    # 水位：压后剩余估算（全部轮文本 - 已压包文本）<= 0.60*budget
    total_estimate = sum(len(text) for _, text in ordered)
    waterline = WATERLINE_RATIO * budget_tokens

    packs: list[tuple[int, int]] = []
    remaining_estimate = total_estimate
    pool = list(candidates)
    while pool and len(packs) < max_packs:
        chunk = pool[:pack_size]
        pool = pool[pack_size:]
        start, end = chunk[0][0], chunk[-1][0]
        packs.append((start, end))
        remaining_estimate -= sum(len(text) for _, text in chunk)
        if remaining_estimate <= waterline:
            break
    return packs


def compress_rounds(
    model: ModelClient, rounds: list[tuple[int, str]], thread_id: str
) -> str:
    """便宜模型调用：一轮区间压成一段摘要文本。

    prompt 形态："压缩以下构建轮次为摘要，保留关键决策与事实，输出一段文本：\\n
    【R1】...\\n【R2】..."；role="compressor"（受控词汇新值——便宜模型子档）。
    返回 result.text。
    """
    lines = "\n".join(f"【R{no}】{text}" for no, text in rounds)
    prompt = (
        "压缩以下构建轮次为摘要，保留关键决策与事实，输出一段文本：\n" + lines
    )
    result = model.complete(
        [{"role": "user", "content": prompt}],
        role=COMPRESSOR_ROLE,
        thread_id=thread_id,
    )
    return str(result.text)


def format_head_pack(packs: Sequence[CompactionPack]) -> str:
    """头部单包（Q56）：全部包合并为一段文本，每包首行
    "【R{start}-R{end}-compact】"标注覆盖轮次，随后摘要正文；包间 "\\n\\n" 分隔。"""
    blocks: list[str] = []
    for pack in packs:
        covered = pack.covered_rounds
        start, end = covered[0], covered[-1]
        blocks.append(f"【R{start}-R{end}-compact】\n{pack.summary}")
    return "\n\n".join(blocks)


def find_error_conjectures(summary: str) -> list[str]:
    """从压缩摘要提取错误猜想：行含"错误"/"失败"/"教训"关键词的行（strip 非空）。"""
    conjectures: list[str] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped and any(k in stripped for k in ("错误", "失败", "教训")):
            conjectures.append(stripped)
    return conjectures


def parse_head_pack(text: str) -> list[tuple[int, int]]:
    """从消息文本解析全部压缩区间目录（头部单包每包首行标记）。"""
    ranges: list[tuple[int, int]] = []
    for match in _COMPACT_HEADER_RE.finditer(text):
        start, end = int(match.group(1)), int(match.group(2))
        ranges.append((start, end))
    return ranges
