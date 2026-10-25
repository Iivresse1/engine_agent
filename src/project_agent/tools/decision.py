"""决策值对象：静态检查、白名单、boundary、interrupt 各层裁决的统一形态。

不保证（调研 §10.3，写进每个模块 docstring 的同一份清单）：
1. 形态学会漏——find -delete、脚本内部逻辑、非枚举删除命令等不在 8 类形态内的风险拦不住；
2. 引号内字面量会误伤——含 ".env" 等敏感词的普通字符串参数会被凭证类命中（fail-closed 方向）；
3. 语义级风险留人工——外发内容审查、供应链 postinstall、不可解析命令替换目标、对话内口头边界、注入语料。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DecisionAction(Enum):
    """裁决三态：allow（放行）/ deny（拒绝）/ ask（升级人工）。"""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class Decision:
    """一次命令（或一次工具调用）的裁决：动作 + 来源规则 + 人可读原因。

    segment 为命中段原文（整条命令命中时等于 command），供审批回调展示。
    """

    action: DecisionAction
    rule_id: str
    reason: str
    command: str = ""
    segment: str = ""


def merge_decisions(
    decisions: list[tuple[str, Decision]], default: Decision
) -> Decision:
    """跨段聚合：取最重（deny > ask > allow），返回带首个最重段 segment 的 Decision。

    decisions 为 (segment_text, decision) 序列；空序列返回 default（其 segment 已由调用方填好）。
    """

    order = {DecisionAction.ALLOW: 0, DecisionAction.ASK: 1, DecisionAction.DENY: 2}
    if not decisions:
        return default
    heaviest = decisions[0][1]
    heaviest_segment = decisions[0][0]
    for segment_text, decision in decisions[1:]:
        if order[decision.action] > order[heaviest.action]:
            heaviest = decision
            heaviest_segment = segment_text
    return Decision(
        action=heaviest.action,
        rule_id=heaviest.rule_id,
        reason=heaviest.reason,
        command=heaviest.command,
        segment=heaviest_segment,
    )
