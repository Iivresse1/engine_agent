"""verifier 节点工厂 + _after_verifier 纯函数（05 票终裁 4/2）。

- 纯代码：todos_all_completed 扫描写入
- LLM：prompt=任务简报+todo 三态板+最后一条 AIMessage 全文；
  解析 task_complete: true/false（fail-closed）；role=verifier
- 计数自增：todos_all_completed and not task_complete → main_loop_count+1
- gate 矩阵（_after_verifier 表驱动）：未清→END / 清而未过→PLANNER /
  双过→END / 计数>=5→LOOP_EXHAUSTED（计数优先序最前）
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END

from project_agent.graph import build_graph
from project_agent.nodes import make_verifier_node
from project_agent.protocol import Role
from project_agent.routing import (
    CONTEXT_ASSEMBLER,
    LOOP_EXHAUSTED,
    PLANNER,
    _after_verifier,
    entry_route,
)
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]
TWO_DONE = [
    {"content": "梳理需求边界", "status": "completed"},
    {"content": "推进对话任务", "status": "completed"},
]


def _cfg(thread: str = "t-verifier") -> dict:
    return {"configurable": {"thread_id": thread}}


# ---- _after_verifier gate 矩阵（验收 1 表驱动） ----

GATE_MATRIX: list[tuple[dict, str]] = [
    # 未清（无论 task_complete）→ END：round 断点收轮，下轮入口路由回 assembler
    ({"todos": TWO_PENDING, "task_complete": False, "main_loop_count": 0}, END),
    ({"todos": TWO_PENDING, "task_complete": True, "main_loop_count": 0}, END),
    # 清而未过 → PLANNER（同轮重新规划）
    ({"todos": TWO_DONE, "task_complete": False, "main_loop_count": 0}, PLANNER),
    # 双过 → END
    ({"todos": TWO_DONE, "task_complete": True, "main_loop_count": 0}, END),
    # 计数 5 → LOOP_EXHAUSTED（优先序最前，压过一切）
    ({"todos": TWO_DONE, "task_complete": False, "main_loop_count": 5}, LOOP_EXHAUSTED),
    ({"todos": TWO_PENDING, "task_complete": False, "main_loop_count": 5}, LOOP_EXHAUSTED),
    ({"todos": TWO_PENDING, "task_complete": True, "main_loop_count": 7}, LOOP_EXHAUSTED),
    # 计数缺省 0
    ({"todos": TWO_DONE, "task_complete": False}, PLANNER),
]


@pytest.mark.parametrize(
    ("state", "expected"),
    GATE_MATRIX,
    ids=[
        "uncleared-false-end",
        "uncleared-true-end",
        "cleared-unpassed-planner",
        "both-passed-end",
        "count5-cleared-loop-exhausted",
        "count5-uncleared-loop-exhausted",
        "count7-loop-exhausted",
        "count-default-0",
    ],
)
def test_after_verifier_gate_matrix(state, expected):
    assert _after_verifier(state) == expected


# ---- verifier 节点 ----

def test_verifier_scans_todos_all_completed_pure_code():
    """纯代码扫描写入：全 completed→True；空表→False（防御）。"""
    node = make_verifier_node(None)
    updates = node({"todos": TWO_PENDING, "actor_messages": [AIMessage(content="x")]}, _cfg())
    assert updates["todos_all_completed"] is False
    updates = node({"todos": TWO_DONE}, _cfg())
    assert updates["todos_all_completed"] is True
    updates = node({"todos": []}, _cfg())
    assert updates["todos_all_completed"] is False  # 空表防御


def test_verifier_llm_parses_task_complete_true():
    model = ScriptedModel(["分析后判定：task_complete: true"])
    node = make_verifier_node(model)
    state = {
        "task_brief": "做个工具",
        "todos": TWO_DONE,
        "actor_messages": [HumanMessage(content="开始"), AIMessage(content="最终产出")],
    }
    updates = node(state, _cfg("tv-1"))
    assert updates["task_complete"] is True
    assert updates["is_docs_finished"] is True  # 05：全方式=task_complete
    assert updates["todos_all_completed"] is True
    call = model.calls[0]
    assert call["role"] == "verifier"
    assert call["thread_id"] == "tv-1"
    # prompt 含任务简报 + todo 三态板 + 最后一条 AIMessage 全文
    prompt = call["messages"][-1]["content"]
    assert "做个工具" in prompt
    assert "completed: 梳理需求边界" in prompt
    assert "最终产出" in prompt


@pytest.mark.parametrize(
    "output",
    ["task_complete: false", "答非所问"],
    ids=["false", "no-match"],
)
def test_verifier_fail_closed(output):
    """解析 fail-closed：无匹配/匹配 false → task_complete=False。"""
    model = ScriptedModel([output])
    node = make_verifier_node(model)
    updates = node(
        {"todos": TWO_DONE, "actor_messages": [AIMessage(content="x")]}, _cfg()
    )
    assert updates["task_complete"] is False


def test_verifier_parses_case_insensitive_true():
    model = ScriptedModel(["结论 Task_Complete: TRUE"])
    node = make_verifier_node(model)
    updates = node({"todos": TWO_DONE, "actor_messages": []}, _cfg())
    assert updates["task_complete"] is True


def test_verifier_model_none_fail_closed():
    """model=None：task_complete=False（fail-closed）+扫描照常。"""
    node = make_verifier_node(None)
    updates = node({"todos": TWO_DONE, "actor_messages": []}, _cfg())
    assert updates["task_complete"] is False
    assert updates["todos_all_completed"] is True


def test_verifier_count_increments_when_cleared_not_passed():
    """计数自增：todos_all_completed and not task_complete → +1。"""
    model = ScriptedModel(["task_complete: false"])
    node = make_verifier_node(model)
    state = {"todos": TWO_DONE, "main_loop_count": 2, "actor_messages": []}
    updates = node(state, _cfg())
    assert updates["main_loop_count"] == 3


@pytest.mark.parametrize(
    ("todos", "task_complete", "count_before", "count_after"),
    [
        (TWO_PENDING, False, 2, 2),  # 未清：不自增
        (TWO_DONE, True, 2, 2),  # 双过：不自增
        (TWO_DONE, False, 2, 3),  # 清而未过：自增
    ],
    ids=["uncleared", "both-passed", "cleared-unpassed"],
)
def test_verifier_count_increment_matrix(todos, task_complete, count_before, count_after):
    outputs = ["task_complete: true"] if task_complete else ["task_complete: false"]
    model = ScriptedModel(outputs)
    node = make_verifier_node(model)
    updates = node(
        {
            "todos": todos,
            "main_loop_count": count_before,
            "actor_messages": [AIMessage(content="x")],
        },
        _cfg(),
    )
    # 未清/双过：节点不写 main_loop_count（保留旧值）；清而未过：+1
    if count_after == count_before:
        assert "main_loop_count" not in updates
    else:
        assert updates["main_loop_count"] == count_after


# ---- 图级：verifier 环 + 入口行 5/7 ----

def test_entry_route_row5_cleared_and_not_complete_to_planner():
    """行 5：todos 清且 task_complete 假 → planner（耗尽恢复路径由 planner 清零）。"""
    state = {
        "task_brief": "x",
        "build_way": "way1",
        "guidance_pref": "auto",
        "todos": TWO_DONE,
        "task_complete": False,
    }
    assert entry_route(state) == PLANNER


def test_entry_route_row7_task_complete_true_to_docs_done():
    """行 7（11 改道）：task_complete 真 → docs_done（demo 决议断点）。"""
    state = {
        "task_brief": "x",
        "build_way": "way1",
        "guidance_pref": "auto",
        "todos": TWO_DONE,
        "task_complete": True,
    }
    assert entry_route(state) == "docs_done"


def test_entry_route_count5_rows_edge_cases():
    """行序边角（终裁字面）：todos pending+count5→CONTEXT_ASSEMBLER；
    清+false+count5→PLANNER（恢复路径）；task_complete 真+任一环 count5→LOOP_EXHAUSTED。"""
    assert (
        entry_route(
            {
                "task_brief": "x",
                "build_way": "way1",
                "guidance_pref": "auto",
                "todos": TWO_PENDING,
                "main_loop_count": 5,
            }
        )
        == CONTEXT_ASSEMBLER
    )
    assert (
        entry_route(
            {
                "task_brief": "x",
                "build_way": "way1",
                "guidance_pref": "auto",
                "todos": TWO_DONE,
                "task_complete": False,
                "main_loop_count": 5,
            }
        )
        == PLANNER
    )
    for count_key in ("main_loop_count", "demo_loop_count", "final_check_loop_count"):
        assert (
            entry_route(
                {
                    "task_brief": "x",
                    "build_way": "way1",
                    "guidance_pref": "auto",
                    "todos": TWO_DONE,
                    "task_complete": True,
                    count_key: 5,
                }
            )
            == LOOP_EXHAUSTED
        )


def test_entry_route_row7_beats_count5():
    """行 7（11 改道）：task_complete 真+计数<5 → docs_done。"""
    assert (
        entry_route(
            {
                "task_brief": "x",
                "build_way": "way1",
                "guidance_pref": "auto",
                "todos": TWO_DONE,
                "task_complete": True,
                "main_loop_count": 4,
            }
        )
        == "docs_done"
    )


def test_graph_work_round_with_verifier():
    """图级工作轮：assembler→actor→verifier→（未清）END round 断点。"""
    model = ScriptedModel(["完成：梳理需求边界。", "task_complete: false"])
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=model)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_pref": "auto",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-v1"),
    )
    assert r["turn_end_reason"] == "round"
    assert r["turn_end_payload"]["round_output"] == "完成：梳理需求边界。"
    assert [item["status"] for item in r["todos"]] == ["completed", "pending"]
    assert r["todos_all_completed"] is False
    assert r["task_complete"] is False
    assert "main_loop_count" not in r or r["main_loop_count"] == 0  # 未清不自增
    assert len(model.calls) == 2  # actor + verifier
    assert model.calls[0]["role"] == "actor"
    assert model.calls[1]["role"] == "verifier"


def test_graph_cleared_unpassed_replans_same_round():
    """清而未过：actor 勾完最后一项→verifier false→同轮 PLANNER 重新规划→END。"""
    model = ScriptedModel(
        ["完成：梳理需求边界。完成：推进对话任务。", "task_complete: false"]
    )
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=model)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_pref": "auto",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "main_loop_count": 1,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-v2"),
    )
    # 同轮重新规划：todos 全新 pending，计数保留（<5）
    assert r["turn_end_reason"] == "round"
    assert [item["status"] for item in r["todos"]] == ["pending", "pending"]
    assert "已列出" in r["turn_end_payload"]["round_output"]
    assert r["main_loop_count"] == 2  # 1 → 自增至 2，planner 保留
    assert r["task_complete"] is False
    assert r["todos_all_completed"] is True  # verifier 扫描时点（重规划前）


def test_graph_both_passed_ends():
    """双过：verifier true→END round 断点（05 放行）。"""
    model = ScriptedModel(
        ["完成：梳理需求边界。完成：推进对话任务。", "task_complete: true"]
    )
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=model)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_pref": "auto",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-v3"),
    )
    assert r["turn_end_reason"] == "round"
    assert r["task_complete"] is True
    assert r["is_docs_finished"] is True
    assert r["todos_all_completed"] is True
    assert "main_loop_count" not in r or r["main_loop_count"] == 0  # 双过不自增


def test_graph_model_none_actor_direct_to_end():
    """model=None：actor→END 直连（跳过 verifier）——05 骨架行为。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_pref": "auto",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-v4"),
    )
    assert r["turn_end_reason"] == "round"
    assert "主环待真模型接入" in r["turn_end_payload"]["round_output"]
    assert "todos_all_completed" not in r or r["todos_all_completed"] is False


def test_role_enum_has_verifier_member():
    assert Role.VERIFIER.value == "verifier"
