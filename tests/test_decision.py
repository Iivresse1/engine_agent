"""Decision 值对象行为：三态枚举、frozen、跨段聚合取最重。"""

from __future__ import annotations

import dataclasses

import pytest

from project_agent.tools.decision import (
    Decision,
    DecisionAction,
    merge_decisions,
)


def test_decision_is_frozen_with_all_fields():
    d = Decision(
        action=DecisionAction.DENY,
        rule_id="static.catastrophic_delete",
        reason="灾难删除形态",
        command="rm -rf /",
        segment="rm -rf /",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.action = DecisionAction.ALLOW  # type: ignore[misc]
    assert d.command == "rm -rf /"
    assert d.segment == "rm -rf /"


def test_merge_picks_heaviest_action_with_first_heaviest_segment():
    allow = Decision(DecisionAction.ALLOW, "allow.read", "ok")
    deny = Decision(DecisionAction.DENY, "static.catastrophic_delete", "boom")
    ask = Decision(DecisionAction.ASK, "whitelist.ask", "confirm?")
    default = Decision(DecisionAction.ALLOW, "allow.read", "ok", segment="all")
    merged = merge_decisions(
        [
            ("git status", allow),
            ("rm -rf /", deny),
            ("docker run x", ask),
        ],
        default,
    )
    assert merged.action is DecisionAction.DENY
    assert merged.rule_id == "static.catastrophic_delete"
    assert merged.segment == "rm -rf /"


def test_merge_empty_returns_default():
    default = Decision(DecisionAction.ASK, "whitelist.miss", "未命中", segment="cmd")
    assert merge_decisions([], default) is default


def test_merge_all_allow_beats_ask_default():
    # 空段时的默认 ask 不得压过非空段的全 allow 聚合
    allow = Decision(DecisionAction.ALLOW, "whitelist.allow_read", "ok")
    default = Decision(DecisionAction.ASK, "whitelist.miss", "未命中", segment="cmd")
    merged = merge_decisions([("npm install", allow), ("npm run build", allow)], default)
    assert merged.action is DecisionAction.ALLOW
    assert merged.segment == "npm install"
