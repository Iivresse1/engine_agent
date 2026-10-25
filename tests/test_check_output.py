"""12 票切片 3：check_proper_output 节点终检环（验收 ④）。

语义校验失败 → 回 planner 开新环（非单轮补丁）：todos 重置为系统性修复项
+ final_check_loop_count 递增；计数=5 → loop_exhausted（scene 含
"终检环计数 5"与失败明细）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_check_node
from project_agent.routing import _after_check
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

DONE_TODOS = [{"content": "写 README", "status": "completed"}]
SEED = {
    "task_brief": "做个记账 CLI",
    "build_way": "way3",
    "todos": DONE_TODOS,
    "task_complete": True,
    "is_docs_finished": True,
    "demo_phase": "skipped",
    "actor_messages": [HumanMessage(content="开始")],
}


def _cfg(thread: str = "t-chk") -> dict:
    return {"configurable": {"thread_id": thread}}


def _seed_way3(root: Path) -> None:
    (root / "README.md").write_text("【R1】# 记账 CLI\n", encoding="utf-8")
    (root / "TODO.md").write_text("【R2】- 勾选\n", encoding="utf-8")
    (root / "目录树.txt").write_text("【R3】root\n", encoding="utf-8")


# —— 节点：不过 → 新环 todos + 计数 ——


def test_check_node_fail_opens_new_loop_with_repair_todo(tmp_path):
    """语义失败 → todos 重置为系统性修复项（planner 见 todos 已设重规划）。"""
    _seed_way3(tmp_path)
    model = ScriptedModel(["semantic_ok: false"] * 3)
    node = make_check_node(model, shared_docs=SharedDocs(tmp_path))

    updates = node(dict(SEED), _cfg("chk-1"))

    assert updates["final_check_loop_count"] == 1
    assert updates["todos"] == [
        {
            "content": "系统性修复：语义:README.md,TODO.md,目录树.txt",
            "status": "pending",
        }
    ]
    assert updates["turn_end_reason"] == "round"
    assert "终检未过" in updates["turn_end_payload"]["round_output"]
    assert "已开新环修复" in updates["turn_end_payload"]["round_output"]


def test_check_node_fail_counts_up_per_recheck(tmp_path):
    _seed_way3(tmp_path)
    model = ScriptedModel(["semantic_ok: false"] * 6)
    node = make_check_node(model, shared_docs=SharedDocs(tmp_path))

    first = node(dict(SEED), _cfg("chk-2"))
    second = node({**SEED, **first}, _cfg("chk-2"))

    assert first["final_check_loop_count"] == 1
    assert second["final_check_loop_count"] == 2


def test_check_node_fail_at_five_loop_exhausted_with_detail(tmp_path):
    """验收 ④后半：终检环计数=5 → loop_exhausted（scene 含计数与失败明细）。"""
    _seed_way3(tmp_path)
    model = ScriptedModel(["semantic_ok: false"] * 3)
    node = make_check_node(model, shared_docs=SharedDocs(tmp_path))

    updates = node(
        {**SEED, "final_check_loop_count": 4}, _cfg("chk-3")
    )

    assert updates["final_check_loop_count"] == 5
    assert updates["turn_end_reason"] == "loop_exhausted"
    payload = updates["turn_end_payload"]
    assert "终检环计数 5" in payload["scene"]
    assert "语义:README.md" in payload["scene"]  # 失败明细
    assert "人工接管" in payload["help_text"]


def test_check_node_missing_detail_first_in_todo(tmp_path):
    """失败明细按序：缺件最前（首项=系统性修复目标）。"""
    (tmp_path / "README.md").write_text("【R1】x\n", encoding="utf-8")
    model = ScriptedModel(["semantic_ok: true"])  # 存在的 README 语义过
    node = make_check_node(model, shared_docs=SharedDocs(tmp_path))

    updates = node(dict(SEED), _cfg("chk-4"))

    assert updates["todos"][0]["content"] == (
        "系统性修复：缺件:TODO.md,目录树.txt"
    )


def test_check_node_without_wiring_returns_skeleton_round():
    node = make_check_node(None, shared_docs=None)
    updates = node(dict(SEED), _cfg("chk-5"))
    assert updates["turn_end_reason"] == "round"


# —— 条件边 _after_check：三态 ——


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"output_clean": True}, "END"),
        ({"final_check_loop_count": 5}, "loop_exhausted"),
        ({"final_check_loop_count": 2}, "planner"),
        ({}, "planner"),
    ],
    ids=["clean-end", "count5-exhausted", "count2-planner", "unset-planner"],
)
def test_after_check_gate(state, expected):
    from langgraph.graph import END

    assert _after_check(state) == (END if expected == "END" else expected)


# —— 图级回放：语义失败 → 新环 → 复检通过 → FINISHED ——


def test_graph_semantic_fail_replans_then_recovers(tmp_path):
    """验收 ④前半：语义失败回 planner 开新环（非补丁）；修复后复检通过。"""
    _seed_way3(tmp_path)
    model = ScriptedModel(
        [
            "终稿报告一。",
            *["semantic_ok: false"] * 3,  # 首检全否 → 开新环
            "完成：梳理需求边界。完成：编写 README。完成：编写 TODO。完成：生成目录树",
            "task_complete: true",  # 新环工作轮双过
            "终稿报告二。",
            *["semantic_ok: true"] * 3,  # 复检通过
        ]
    )
    app = build_graph(
        checkpointer=InMemorySaver(),
        model=model,
        workspace_root=tmp_path,
    )
    cfg = _cfg("g-chk-1")

    # 首轮：FINALIZER→CHECK（语义失败）→PLANNER 开新环
    r1 = app.invoke(dict(SEED), cfg)
    assert r1["turn_end_reason"] == "round"
    assert r1["final_check_loop_count"] == 1
    assert [t["status"] for t in r1["todos"]] == ["pending"] * 4  # 重规划模板板

    # 次轮：工作轮勾全+双过 → END 收轮（回主线）
    r2 = app.invoke({"actor_messages": [HumanMessage(content="修")]}, cfg)
    assert r2["turn_end_reason"] == "round"
    assert r2["task_complete"] is True

    # 三轮：复进终检（skipped 直通行 8）→ 复检通过 → FINISHED
    r3 = app.invoke({"actor_messages": [HumanMessage(content="再检")]}, cfg)
    assert r3["turn_end_reason"] == "finished"
    assert r3["output_clean"] is True
    paths = r3["turn_end_payload"]["delivery_paths"]
    assert paths["backup"] == str(tmp_path / "deliverables_backup")
    assert paths["clean"] == str(tmp_path / "deliverables_clean")


def test_graph_fifth_recheck_failure_hits_loop_exhausted(tmp_path):
    """验收 ④后半图级：终检环计数 5 → loop_exhausted（scene 含失败明细）。"""
    _seed_way3(tmp_path)
    # 5 轮终检全失败；每环中间夹一个工作轮（勾全+双过）回到终检
    script: list[str] = []
    for i in range(5):
        script.append(f"终稿报告{i}。")  # finalizer
        script.extend(["semantic_ok: false"] * 3)  # check 全否
        if i < 4:
            script.append(
                "完成：梳理需求边界。完成：编写 README。完成：编写 TODO。完成：生成目录树"
            )
            script.append("task_complete: true")
    model = ScriptedModel(script)
    app = build_graph(
        checkpointer=InMemorySaver(),
        model=model,
        workspace_root=tmp_path,
    )
    cfg = _cfg("g-chk-2")

    state = app.invoke(dict(SEED), cfg)
    assert state["turn_end_reason"] == "round"
    assert state["final_check_loop_count"] == 1

    for i in range(2, 5):
        # 工作轮（勾全+双过）→ 回主线收轮
        state = app.invoke({"actor_messages": [HumanMessage(content="修")]}, cfg)
        assert state["task_complete"] is True
        # 复进终检 → 仍失败 → 计数 i
        state = app.invoke({"actor_messages": [HumanMessage(content="再检")]}, cfg)
        assert state["turn_end_reason"] == "round"
        assert state["final_check_loop_count"] == i

    # 第 5 检：工作轮双过后终检计数已达 4 → 本次失败 ==5 → loop_exhausted
    state = app.invoke({"actor_messages": [HumanMessage(content="修")]}, cfg)
    assert state["task_complete"] is True
    r = app.invoke({"actor_messages": [HumanMessage(content="终检")]}, cfg)
    assert r["turn_end_reason"] == "loop_exhausted"
    assert "终检环计数 5" in r["turn_end_payload"]["scene"]
    assert "语义:" in r["turn_end_payload"]["scene"]
