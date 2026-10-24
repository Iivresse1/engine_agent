"""断点协议表（7 种 reason）的形状契约——spec v1.1『状态契约』节的代码化断言。"""

from __future__ import annotations

import pytest

from project_agent.protocol import (
    BREAKPOINT_PROTOCOL,
    Fusion,
    PayloadError,
    TurnEndReason,
    validate_payload,
)

VALID_PAYLOADS = {
    TurnEndReason.ROUND: {"round_output": "本轮产出概览", "todo_board": ["pending: 搭骨架"]},
    TurnEndReason.QUESTION: {
        "question_text": "你想用什么构建方式？",
        "options": ["对话", "轻 grill", "简化文档", "完整文档"],
        "asker": "actor",
    },
    TurnEndReason.CHOICE_BUILD_WAY: {
        "options": ["way1", "way2", "way3", "way4"],
        "recommendation": "way3",
        "recommendation_reason": "个人作品有沉淀不臃肿",
    },
    TurnEndReason.CHOICE_PROPOSAL: {
        "proposal_summaries": ["方案A", "方案B", "方案C"],
    },
    TurnEndReason.DOCS_DONE: {
        "deliverables_overview": "README/TODO/目录树",
        "options": ["构建 demo", "自定义答案"],
    },
    TurnEndReason.LOOP_EXHAUSTED: {
        "scene": "主环计数=5；todos 3 项未清",
        "help_text": "请人工接管",
    },
    TurnEndReason.FINISHED: {
        "delivery_paths": {"backup": "backup/", "clean": "clean/"},
    },
}


def test_protocol_covers_all_seven_reasons():
    assert {r.value for r in TurnEndReason} == {
        "round",
        "question",
        "choice:build_way",
        "choice:proposal",
        "docs_done",
        "loop_exhausted",
        "finished",
    }
    assert set(BREAKPOINT_PROTOCOL) == set(TurnEndReason)


@pytest.mark.parametrize(
    ("reason", "expected_fusion"),
    [
        (TurnEndReason.ROUND, Fusion.MAINLINE),
        (TurnEndReason.QUESTION, Fusion.ASKER),
        (TurnEndReason.CHOICE_BUILD_WAY, Fusion.RESOLUTION),
        (TurnEndReason.CHOICE_PROPOSAL, Fusion.RESOLUTION),
        (TurnEndReason.DOCS_DONE, Fusion.RESOLUTION),
        (TurnEndReason.LOOP_EXHAUSTED, Fusion.FREE_MAINLINE),
        (TurnEndReason.FINISHED, Fusion.TERMINAL),
    ],
    ids=lambda x: x.value if isinstance(x, TurnEndReason) else x.value,
)
def test_fusion_targets_match_spec_table(reason, expected_fusion):
    assert BREAKPOINT_PROTOCOL[reason].fusion is expected_fusion


@pytest.mark.parametrize("reason", list(TurnEndReason), ids=lambda r: r.value)
def test_valid_payload_passes(reason):
    payload = VALID_PAYLOADS[reason]
    result = validate_payload(reason, payload)
    assert result == payload


@pytest.mark.parametrize("reason", list(TurnEndReason), ids=lambda r: r.value)
def test_missing_required_field_rejected(reason):
    entry = BREAKPOINT_PROTOCOL[reason]
    field = entry.required_payload_fields[0]
    payload = {k: v for k, v in VALID_PAYLOADS[reason].items() if k != field}
    with pytest.raises(PayloadError):
        validate_payload(reason, payload)


def test_unknown_payload_field_rejected():
    payload = dict(VALID_PAYLOADS[TurnEndReason.ROUND])
    payload["surprise"] = "不在受控形状内"
    with pytest.raises(PayloadError):
        validate_payload(TurnEndReason.ROUND, payload)


def test_dashboard_fields_cover_spec_contract():
    from project_agent.state import Dashboard, GraphState

    dash = set(Dashboard.__optional_keys__) | set(Dashboard.__required_keys__)
    expected = {
        "task_brief",
        "build_way",
        "guidance_mode",
        "user_mode",
        "guidance_pref",
        "decision_mode",
        "skill_packs",
        "proposal_set",
        "selected_proposal",
        "todos",
        "todos_all_completed",
        "task_complete",
        "is_docs_finished",
        "output_clean",
        "main_loop_count",
        "demo_loop_count",
        "final_check_loop_count",
        "demo_phase",
        "round_summary",
        "round_count",
        "notes_version",
        "guidance_read_version",
        "current_scope",
        "turn_end_reason",
        "turn_end_payload",
        "awaiting_input_from",
        "final_report",
    }
    assert dash == expected
    graph_keys = set(GraphState.__optional_keys__) | set(GraphState.__required_keys__)
    assert dash <= graph_keys
    assert {"actor_messages", "demo_messages", "assembled_context"} <= graph_keys
    assert "resolution_inputs" in graph_keys
