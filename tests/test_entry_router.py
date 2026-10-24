"""入口路由真值表前 3 行：相位重建（纯代码，零 LLM）。"""

from __future__ import annotations

import pytest

from project_agent.routing import ENTRY_TRUTH_TABLE, entry_route


@pytest.mark.parametrize(
    ("dashboard", "expected"),
    ENTRY_TRUTH_TABLE,
    ids=[f"row{i + 1}" for i in range(len(ENTRY_TRUTH_TABLE))],
)
def test_entry_truth_table(dashboard, expected):
    assert entry_route(dashboard) == expected


def test_task_brief_takes_precedence_over_build_way():
    """两者都缺时先问任务（真值表行序即优先级）。"""
    assert entry_route({}) == "ask_tasks"
    assert entry_route({"build_way": ""}) == "ask_tasks"


def test_empty_string_counts_as_unset():
    assert entry_route({"task_brief": "", "build_way": ""}) == "ask_tasks"
    assert entry_route({"task_brief": "x", "build_way": ""}) == "build_ways"


def test_other_dashboard_fields_do_not_affect_route():
    """01 票只实现前 3 行：其余字段存在与否不改变路由。"""
    state = {
        "task_brief": "x",
        "build_way": "way4",
        "todos": [{"content": "t", "status": "pending"}],
        "main_loop_count": 3,
        "turn_end_reason": "round",
    }
    assert entry_route(state) == "placeholder"
