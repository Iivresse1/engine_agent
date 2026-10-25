"""12 票切片 4：全 lifespan 回放（验收 ①⑤⑥ 汇总勾验）。

seed 直达（way3+todos 全清+task_complete 真+is_docs_finished 真+
demo_phase=skipped+tmp 工作区预写带【R#】的 3 份交付物）→
FINALIZER→CHECK→FINISHED 断点（delivery_paths 双份）→干净版零【R#】
残留 + 备份版保留；Store 跨 thread 检索；skipped 直通（入口行 8）。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.memory_store import InMemoryStore
from tests.doubles.fake_model import ScriptedModel

pytestmark = __import__("pytest").mark.replay

REPORT = "成果：三份文档齐备可交付。经验教训：先对齐范围再动笔，切片推进。"

SEED = {
    "task_brief": "做个记账 CLI",
    "build_way": "way3",
    "todos": [{"content": "写 README", "status": "completed"}],
    "task_complete": True,
    "is_docs_finished": True,
    "demo_phase": "skipped",
    "round_summary": "最后一轮写完 TODO 与目录树",
    "actor_messages": [HumanMessage(content="开始")],
}


def _cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def _seed_way3(root: Path) -> None:
    """tmp 工作区预写带【R#】的 3 份交付物（含区间压缩形态与行内标记）。"""
    (root / "README.md").write_text(
        "【R1】# 记账 CLI\n【R2】轻量命令行工具。\n【R1-R3-compact】\n",
        encoding="utf-8",
    )
    (root / "TODO.md").write_text("【R3】- 需求：记账\n【R4】- 已全部完成\n", encoding="utf-8")
    (root / "目录树.txt").write_text("【R5】root/\n【R6】├── main.py\n", encoding="utf-8")
    # 共享区伴生文件（快照全量 .md/.txt）
    (root / "NOTES.md").write_text("【R1】- 首条记录\n", encoding="utf-8")
    (root / "BUILD_LOG.md").write_text("【R1】第一轮生成物\n\n", encoding="utf-8")


def _app(tmp_path: Path, model, store=None):
    return build_graph(
        checkpointer=InMemorySaver(),
        model=model,
        workspace_root=tmp_path,
        store=store,
    )


def test_full_lifespan_replay_double_delivery_zero_residue(tmp_path):
    """验收 ①：全 lifespan 双份交付、零【R#】残留。"""
    _seed_way3(tmp_path)
    model = ScriptedModel([REPORT, *["semantic_ok: true"] * 3])
    app = _app(tmp_path, model)
    r = app.invoke(dict(SEED), _cfg("life-1"))

    # FINISHED 断点：delivery_paths 双份
    assert r["turn_end_reason"] == "finished"
    assert r["final_report"] == REPORT
    paths = r["turn_end_payload"]["delivery_paths"]
    backup, clean = Path(paths["backup"]), Path(paths["clean"])
    assert backup == tmp_path / "deliverables_backup"
    assert clean == tmp_path / "deliverables_clean"

    # 干净版：三份交付物零【R#】残留，内容=原文剥标记
    clean_readme = (clean / "README.md").read_text(encoding="utf-8")
    assert clean_readme == "# 记账 CLI\n轻量命令行工具。\n\n"
    assert "【R" not in clean_readme
    assert "【R" not in (clean / "TODO.md").read_text(encoding="utf-8")
    assert "【R" not in (clean / "目录树.txt").read_text(encoding="utf-8")
    # 备份版保留：交付物 + 共享区伴生文件（.md/.txt 全量）
    assert "【R1】" in (backup / "README.md").read_text(encoding="utf-8")
    assert "【R1】" in (backup / "NOTES.md").read_text(encoding="utf-8")
    assert "【R1】" in (backup / "BUILD_LOG.md").read_text(encoding="utf-8")
    # 原文不动（磁盘为事实来源——ADR-0004）
    assert "【R1】" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_full_lifespan_store_cross_thread_retrieval(tmp_path):
    """验收 ⑤：final_report 入 Store——新会话视角跨 thread 检索读回。"""
    _seed_way3(tmp_path)
    model = ScriptedModel([REPORT, *["semantic_ok: true"] * 3])
    store = InMemoryStore()
    app = _app(tmp_path, model, store=store)
    app.invoke(dict(SEED), _cfg("life-store"))

    # 模拟新会话（不同 thread 的视角）：key=task_brief 原文（简化终裁）
    assert store.get("final_report:做个记账 CLI") == REPORT
    assert store.get("final_report:别的任务") is None


def test_full_lifespan_skipped_demo_direct_to_finalizer(tmp_path):
    """验收 ⑥后半：skipped demo 直通终检（入口行 8）——seed invoke 即 FINISHED。"""
    _seed_way3(tmp_path)
    model = ScriptedModel([REPORT, *["semantic_ok: true"] * 3])
    app = _app(tmp_path, model)
    # 单次 invoke：START→入口行 8→FINALIZER→CHECK→FINISHED（零中间断点）
    r = app.invoke(dict(SEED), _cfg("life-skip"))
    assert r["turn_end_reason"] == "finished"
    assert r["output_clean"] is True
