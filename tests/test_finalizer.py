"""12 票切片 2：InMemoryStore + finalizer 节点 + 图接线（FINALIZER 三入口）。

- memory_store.py：InMemoryStore（dict 按 key 存取，跨 thread 长期记忆）
- make_finalizer_node(model, store)：final_report 产出 + Store 存取
- 图接线：入口行 8（is_docs_finished 真且 demo_phase=="skipped"→FINALIZER）；
  DOCS_DONE 条件边 skipped/done→FINALIZER；DEMO_AGENT→FINALIZER 边改向
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.memory_store import InMemoryStore
from project_agent.nodes import make_finalizer_node
from project_agent.routing import FINALIZER, entry_route
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

DONE_TODOS = [{"content": "写 README", "status": "completed"}]
REPORT = "项目完成：三份文档齐备。经验教训：先对齐范围再动笔。"

# seed：docs 完成 + demo 已跳过——直达 FINALIZER 的会话形状
SEED = {
    "task_brief": "做个记账 CLI",
    "build_way": "way3",
    "todos": DONE_TODOS,
    "task_complete": True,
    "is_docs_finished": True,
    "demo_phase": "skipped",
    "actor_messages": [HumanMessage(content="开始")],
}


def _cfg(thread: str = "t-fin") -> dict:
    return {"configurable": {"thread_id": thread}}


# —— InMemoryStore：dict 按 key 存取 ——


def test_store_put_get_roundtrip():
    store = InMemoryStore()
    store.put("k", "v")
    assert store.get("k") == "v"
    assert store.get("absent") is None


def test_store_overwrite_last_wins():
    store = InMemoryStore()
    store.put("k", "v1")
    store.put("k", "v2")
    assert store.get("k") == "v2"


def test_store_multiple_keys_independent():
    store = InMemoryStore()
    store.put("a", 1)
    store.put("b", 2)
    assert store.get("a") == 1
    assert store.get("b") == 2


# —— finalizer 节点：final_report 产出 + Store 存取 ——


def test_finalizer_node_prompt_summary_and_report(tmp_path):
    """prompt 汇总四要素（brief/way/round_summary/NOTES 前 5 条）→ final_report。"""
    model = ScriptedModel([REPORT])
    store = InMemoryStore()
    # NOTES.md 概览 6 条——只取前 5
    (tmp_path / "NOTES.md").write_text(
        "【R1】- 第一条\n【R2】- 第二条\n【R3】- 第三条\n【R4】- 第四条\n【R5】- 第五条\n【R6】- 第六条\n",
        encoding="utf-8",
    )
    node = make_finalizer_node(model, store=store, shared_docs=SharedDocs(tmp_path))

    state = {
        **SEED,
        "round_summary": "最后一轮写完 TODO",
        "demo_messages": [HumanMessage(content="demo")],
    }
    updates = node(state, _cfg("fin-1"))

    call = model.calls[0]
    assert call["role"] == "finalizer"
    assert call["thread_id"] == "fin-1"
    content = call["messages"][0]["content"]
    assert "任务：做个记账 CLI" in content
    assert "方式：way3" in content
    assert "最后轮摘要：最后一轮写完 TODO" in content
    assert "第一条" in content and "第五条" in content
    assert "第六条" not in content  # 前 5 条封顶
    assert "final_report" in content
    # 产出：final_report 写 state + 入 Store（key=task_brief 原文）
    assert updates["final_report"] == REPORT
    assert store.get("final_report:做个记账 CLI") == REPORT


def test_finalizer_node_no_notes_says_empty(tmp_path):
    model = ScriptedModel([REPORT])
    node = make_finalizer_node(
        model, store=InMemoryStore(), shared_docs=SharedDocs(tmp_path)
    )
    node(dict(SEED), _cfg("fin-2"))
    content = model.calls[0]["messages"][0]["content"]
    assert "无" in content.split("Notepad 要点")[1].split("\n")[0]


def test_finalizer_node_without_store_writes_report_only(tmp_path):
    """store=None（轻实现默认）：final_report 仍产，零 Store 写。"""
    model = ScriptedModel([REPORT])
    node = make_finalizer_node(
        model, store=None, shared_docs=SharedDocs(tmp_path)
    )
    updates = node(dict(SEED), _cfg("fin-3"))
    assert updates["final_report"] == REPORT


def test_finalizer_node_round_end_breakpoint(tmp_path):
    model = ScriptedModel([REPORT])
    node = make_finalizer_node(
        model, store=InMemoryStore(), shared_docs=SharedDocs(tmp_path)
    )
    updates = node(dict(SEED), _cfg("fin-4"))
    assert updates["turn_end_reason"] == "round"
    assert REPORT in updates["turn_end_payload"]["round_output"]


# —— 入口路由行 8：is_docs_finished 真且 demo_phase=="skipped"→FINALIZER ——


def test_entry_row8_docs_finished_skipped_routes_to_finalizer():
    dashboard = {
        "task_brief": "x",
        "build_way": "way1",
        "todos": [{"content": "a", "status": "completed"}],
        "task_complete": True,
        "is_docs_finished": True,
        "demo_phase": "skipped",
    }
    assert entry_route(dashboard) == FINALIZER


def test_entry_row8_not_triggered_when_demo_building():
    """demo 构建中仍走 demo 行（行 7 前）；finalizer 只接管 skipped 终态。"""
    dashboard = {
        "task_brief": "x",
        "build_way": "way1",
        "todos": [{"content": "a", "status": "completed"}],
        "task_complete": True,
        "demo_phase": "building",
    }
    assert entry_route(dashboard) == "demo_agent"


def test_entry_row8_not_triggered_without_docs_finished():
    dashboard = {
        "task_brief": "x",
        "build_way": "way1",
        "todos": [{"content": "a", "status": "completed"}],
        "task_complete": True,
        "demo_phase": "skipped",
    }
    assert entry_route(dashboard) == "docs_done"  # 未终态：仍去决议断点


# —— 图接线：三入口汇入 FINALIZER ——


def test_graph_entry_row8_reaches_finalizer(tmp_path):
    """验收 ⑥ 后半：skipped demo 直通终检——入口行 8 → FINALIZER 轮。"""
    model = ScriptedModel([REPORT, *["semantic_ok: true"] * 3])  # finalizer + check×3
    app = build_graph(
        checkpointer=InMemorySaver(),
        model=model,
        workspace_root=tmp_path,
        store=InMemoryStore(),
    )
    _seed_way3(tmp_path)
    r = app.invoke(dict(SEED), _cfg("g-fin-1"))
    # finalizer 轮收 round 断点（FINALIZER→CHECK→FINISHED 断点收轮）
    assert r["final_report"] == REPORT
    assert r["turn_end_reason"] == "finished"
    paths = r["turn_end_payload"]["delivery_paths"]
    assert paths["backup"] == str(tmp_path / "deliverables_backup")
    assert paths["clean"] == str(tmp_path / "deliverables_clean")


def test_graph_store_receives_report_cross_thread(tmp_path):
    """验收 ⑤：final_report 入 Store——模拟新会话跨 thread 检索读回。"""
    model = ScriptedModel([REPORT, *["semantic_ok: true"] * 3])
    store = InMemoryStore()
    app = build_graph(
        checkpointer=InMemorySaver(),
        model=model,
        workspace_root=tmp_path,
        store=store,
    )
    _seed_way3(tmp_path)
    app.invoke(dict(SEED), _cfg("g-fin-2"))
    # 跨 thread（新会话视角）：key=task_brief 原文（简化终裁）
    assert store.get("final_report:做个记账 CLI") == REPORT


def test_graph_demo_agent_edges_to_finalizer_after_demo(tmp_path):
    """DEMO_AGENT→FINALIZER 边改向：demo 完成后进终检（不再 END 收轮）。"""
    model = ScriptedModel(
        [
            "写入：demo/main.py\nprint('hi')",  # demo 轮
            REPORT,  # finalizer
            *["semantic_ok: true"] * 3,  # check×3
        ]
    )
    app = build_graph(
        checkpointer=InMemorySaver(),
        model=model,
        workspace_root=tmp_path,
        store=InMemoryStore(),
    )
    cfg = _cfg("g-fin-3")
    _seed_way3(tmp_path)
    r0 = app.invoke(
        {
            "task_brief": "做个记账 CLI",
            "build_way": "way3",
            "todos": DONE_TODOS,
            "task_complete": True,
            "actor_messages": [HumanMessage(content="开始")],
        },
        cfg,
    )
    assert r0["turn_end_reason"] == "docs_done"
    r1 = app.invoke({"resolution_inputs": ["构建 demo"]}, cfg)
    # demo 轮不再收轮：同轮接 FINALIZER → CHECK → FINISHED
    assert r1["turn_end_reason"] == "finished"
    assert (tmp_path / "demo" / "main.py").is_file()
def test_graph_docs_done_skipped_edges_to_finalizer(tmp_path):
    """DOCS_DONE 条件边改向：skipped→FINALIZER（11 票原 END 边被替换）。"""
    model = ScriptedModel([REPORT, *["semantic_ok: true"] * 4])
    app = build_graph(
        checkpointer=InMemorySaver(),
        model=model,
        workspace_root=tmp_path,
        store=InMemoryStore(),
    )
    cfg = _cfg("g-fin-4")
    _seed_way3(tmp_path)
    r0 = app.invoke(
        {
            "task_brief": "做个记账 CLI",
            "build_way": "way3",
            "todos": DONE_TODOS,
            "task_complete": True,
            "actor_messages": [HumanMessage(content="开始")],
        },
        cfg,
    )
    assert r0["turn_end_reason"] == "docs_done"
    r1 = app.invoke({"resolution_inputs": ["跳过"]}, cfg)
    assert r1["demo_phase"] == "skipped"
    # skipped 后同轮直通终检：FINISHED
    assert r1["turn_end_reason"] == "finished"
    assert r1["final_report"] == REPORT


def _seed_way3(root: Path) -> None:
    (root / "README.md").write_text("【R1】# 记账 CLI\n", encoding="utf-8")
    (root / "TODO.md").write_text("【R2】- 勾选\n", encoding="utf-8")
    (root / "目录树.txt").write_text("【R3】root\n", encoding="utf-8")
