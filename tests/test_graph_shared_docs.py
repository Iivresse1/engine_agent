"""06 票图级共享文档区：workspace_root 注入 → actor 产【R#】落盘跨轮持续。

ScriptedModel 驱动两轮工作轮：R1/R2 条目落盘、切片检索、notes_version
跨轮递增（checkpointer 持续 round_count）。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]

R1_TEXT = "完成：梳理需求边界。记录：登录页要用浅色主题"
R2_TEXT = "继续推进。记录：接口超时需设 30 秒。记录：错误码统一 5 位"


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def _cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def _seed() -> dict:
    return {
        "task_brief": "想法",
        "build_way": "way1",
        "todos": TWO_PENDING,
        "actor_messages": [HumanMessage(content="开始")],
    }


def test_graph_workspace_root_two_rounds_r1_r2_on_disk(tmp_path: Path):
    """两轮工作：R1/R2 条目落盘、切片检索、notes_version/round_count 跨轮递增。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            R1_TEXT,  # 工作轮 1：actor（勾第一项 + 1 条记录）
            "task_complete: false",
            R2_TEXT,  # 工作轮 2：actor（1 条记录 + 1 条记录）
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-shared-1")

    r1 = app.invoke(_seed(), cfg)
    assert r1["round_count"] == 1
    assert r1["notes_version"] == 1
    r2 = app.invoke(_say("继续"), cfg)
    assert r2["round_count"] == 2  # 跨 invoke 持续（checkpointer）
    assert r2["notes_version"] == 3  # 1 + 2 条

    docs = SharedDocs(tmp_path)
    # 每轮生成物带【R#】且连续编号
    assert docs.read_rounds() == [
        (1, f"【R1】{R1_TEXT}"),
        (2, f"【R2】{R2_TEXT}"),
    ]
    # 切片检索只返回该轮
    assert docs.read_round(2) == f"【R2】{R2_TEXT}"
    # Notepad 条目带【R#】：R1 一条、R2 两条（段尾空白 strip，句读保留）
    assert docs.notepad_entries() == [
        (1, "登录页要用浅色主题"),
        (2, "接口超时需设 30 秒。"),
        (2, "错误码统一 5 位"),
    ]
    # 落盘的是字面文件（磁盘为共享事实来源）
    assert (tmp_path / "BUILD_LOG.md").read_text(encoding="utf-8").startswith("【R1】")
    assert (tmp_path / "NOTES.md").exists()


def test_graph_workspace_root_none_writes_no_files(tmp_path: Path):
    """workspace_root=None（缺省）：图行为与 05 一致——不落盘任何共享文档。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            R1_TEXT,
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model)  # 不传 workspace_root
    r1 = app.invoke(_seed(), _cfg("g-shared-2"))
    assert r1["turn_end_reason"] == "round"
    assert "round_count" not in r1  # 05 行为：仪表盘不写
    assert "notes_version" not in r1
    assert list(tmp_path.iterdir()) == []  # 零落盘


def test_graph_workspace_root_with_model_none_still_inert(tmp_path: Path):
    """model=None 优先于 workspace_root：骨架 inert 不落盘（CLI 零改动依据）。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, workspace_root=tmp_path)
    r = app.invoke(_seed(), _cfg("g-shared-3"))
    assert r["turn_end_reason"] == "round"
    assert "主环待真模型接入" in r["turn_end_payload"]["round_output"]
    assert list(tmp_path.iterdir()) == []


# —— 06 验收 4：隔离红线——跨角色只经共享文档区 ——

DEMO_PRIVATE_MARKER = "DEMO_PRIVATE_MARKER_G06"


def test_graph_isolation_redline_shared_docs_free_of_demo_history(tmp_path: Path):
    """seed demo_messages 带独特标记 → 两轮工作 → BUILD_LOG/NOTES 内容绝不含
    marker：actor 落盘的只有自己的产出（跨角色信息只走磁盘共享文档区）。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            R1_TEXT,
            "task_complete: false",
            R2_TEXT,
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-redline-06")
    seed = {**_seed(), "demo_messages": [HumanMessage(content=f"demo 私语 {DEMO_PRIVATE_MARKER}")]}
    r1 = app.invoke(seed, cfg)
    r2 = app.invoke(_say("继续"), cfg)
    assert r1["turn_end_reason"] == "round"
    assert r2["turn_end_reason"] == "round"
    assert len(model.calls) == 4  # 两轮 actor+verifier

    build_log = (tmp_path / "BUILD_LOG.md").read_text(encoding="utf-8")
    notes = (tmp_path / "NOTES.md").read_text(encoding="utf-8")
    assert DEMO_PRIVATE_MARKER not in build_log
    assert DEMO_PRIVATE_MARKER not in notes
    # 模型调用输入同样绝不含 marker（私有历史不入彼此上下文）
    for call in model.calls:
        for message in call["messages"]:
            assert DEMO_PRIVATE_MARKER not in str(message.values())


def test_read_round_cross_role_retrieval_flows_via_disk_not_history(tmp_path: Path):
    """ReadProjectDocs 语义（验收 4）：read_round 检索跨角色可读——信息经磁盘
    流动非消息历史。另一角色以全新 SharedDocs 视角读同一工作区即可检索，
    无需任何 state/消息历史；demo_messages 全程不变。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            R1_TEXT,
            "task_complete: false",
            R2_TEXT,
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-crossread-06")
    app.invoke(_seed(), cfg)
    r2 = app.invoke(_say("继续"), cfg)

    # 另一角色（如 DemoAgent）零共享 state，纯磁盘检索
    reader = SharedDocs(tmp_path)
    assert reader.read_round(1) == f"【R1】{R1_TEXT}"
    assert reader.read_round(2) == f"【R2】{R2_TEXT}"
    assert reader.notepad_read(round_no=2) == [
        (2, "接口超时需设 30 秒。"),
        (2, "错误码统一 5 位"),
    ]
    # 信息没经消息历史流动：demo_messages 从未被写入
    assert "demo_messages" not in r2 or r2["demo_messages"] == []
    # 共享文档区是唯一跨角色介质：Notepad 全量可读
    assert len(reader.notepad_entries()) == 3
