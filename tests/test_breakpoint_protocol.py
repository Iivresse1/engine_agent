"""断点协议表（7 种 reason）的形状契约——spec v1.1『状态契约』节的代码化断言。"""

from __future__ import annotations

import pytest

from project_agent.protocol import (
    BREAKPOINT_PROTOCOL,
    Fusion,
    PayloadError,
    RoundEndReason,
    validate_payload,
)

VALID_PAYLOADS = {
    RoundEndReason.ROUND: {"round_output": "本轮产出概览", "todo_board": ["pending: 搭骨架"]},
    RoundEndReason.QUESTION: {
        "question_text": "构建方式 —— 决定 agent 用多重的流程陪你把这个项目做出来",
        "explanation": "影响流程重量与文档产出",
        "options": [
            "对话 —— 像聊天一样推进，不产出文档",
            "轻 grill —— 少量追问压测计划，文档极简",
        ],
        "asker": "actor",
    },
    RoundEndReason.CHOICE_BUILD_WAY: {
        "explanation": "决定 agent 用多重的流程陪你把这个项目做出来",
        "options": ["way1", "way2", "way3", "way4"],
        "recommendation": "way3",
        "recommendation_reason": "个人作品有沉淀不臃肿",
    },
    RoundEndReason.CHOICE_PROPOSAL: {
        "proposal_summaries": ["方案A", "方案B", "方案C"],
    },
    RoundEndReason.DOCS_DONE: {
        "deliverables_overview": "README/TODO/目录树",
        "options": ["构建 demo", "自定义答案"],
    },
    RoundEndReason.LOOP_EXHAUSTED: {
        "scene": "主环计数=5；todos 3 项未清",
        "help_text": "请人工接管",
    },
    RoundEndReason.FINISHED: {
        "delivery_paths": {"backup": "backup/", "clean": "clean/"},
    },
}


def test_protocol_covers_all_seven_reasons():
    assert {r.value for r in RoundEndReason} == {
        "round",
        "question",
        "choice:build_way",
        "choice:proposal",
        "docs_done",
        "loop_exhausted",
        "finished",
    }
    assert set(BREAKPOINT_PROTOCOL) == set(RoundEndReason)


@pytest.mark.parametrize(
    ("reason", "expected_fusion"),
    [
        (RoundEndReason.ROUND, Fusion.MAINLINE),
        (RoundEndReason.QUESTION, Fusion.ASKER),
        (RoundEndReason.CHOICE_BUILD_WAY, Fusion.RESOLUTION),
        (RoundEndReason.CHOICE_PROPOSAL, Fusion.RESOLUTION),
        (RoundEndReason.DOCS_DONE, Fusion.RESOLUTION),
        (RoundEndReason.LOOP_EXHAUSTED, Fusion.FREE_MAINLINE),
        (RoundEndReason.FINISHED, Fusion.TERMINAL),
    ],
    ids=lambda x: x.value if isinstance(x, RoundEndReason) else x.value,
)
def test_fusion_targets_match_spec_table(reason, expected_fusion):
    assert BREAKPOINT_PROTOCOL[reason].fusion is expected_fusion


@pytest.mark.parametrize("reason", list(RoundEndReason), ids=lambda r: r.value)
def test_valid_payload_passes(reason):
    payload = VALID_PAYLOADS[reason]
    result = validate_payload(reason, payload)
    assert result == payload


@pytest.mark.parametrize("reason", list(RoundEndReason), ids=lambda r: r.value)
def test_missing_required_field_rejected(reason):
    entry = BREAKPOINT_PROTOCOL[reason]
    field = entry.required_payload_fields[0]
    payload = {k: v for k, v in VALID_PAYLOADS[reason].items() if k != field}
    with pytest.raises(PayloadError):
        validate_payload(reason, payload)


def test_unknown_payload_field_rejected():
    payload = dict(VALID_PAYLOADS[RoundEndReason.ROUND])
    payload["surprise"] = "不在受控形状内"
    with pytest.raises(PayloadError):
        validate_payload(RoundEndReason.ROUND, payload)


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
        "teach_me_pref",  # 13 票：ask 模式"以后都深度教学"决议（"" | "always"）
        "compacted_rounds",  # 08：仪表盘 +compacted_rounds，spec 待 Lead 补录 v1.4
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
