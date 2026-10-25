"""07 票切片 4：way4 DocScaffold 框架先行 + 文档逐轮生长。

- context_assembler：way4 且工作区无交付物框架（首个文档不存在）→
  system 追加"构建方式为完整文档：先以占位框架落盘各交付物（每份文档标题+空节），随后逐轮 grilling 填充。"
- grilling 身体首轮（round_count==1 且 way4 且 shared_docs）→ 先为每份
  DELIVERABLE_SETS["way4"] 文档写占位框架（f"# {stem}\\n\\n（待填）\\n"），
  已存在则跳过（幂等），再走模型调用
- 逐轮生长断言：两轮后文件内容增长（非一次倾倒）
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.deliverables import DELIVERABLE_SETS
from project_agent.graph import build_graph
from project_agent.nodes import (
    make_actor_node,
    make_assembler_node,
)
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

SCAFFOLD_SUFFIX = (
    "\n构建方式为完整文档：先以占位框架落盘各交付物（每份文档标题+空节），随后逐轮 grilling 填充。"
)

WAY4_TODOS = [
    {"content": "搭建文档框架", "status": "pending"},
    {"content": "填写核心文档", "status": "pending"},
]


def _cfg(thread: str = "t-scaf") -> dict:
    return {"configurable": {"thread_id": thread}}


def _assembled(way: str, todos: list) -> dict:
    return {
        "system": f"你是构建 agent。当前方式 {way}，指引 off，待办 {len(todos)} 项",
        "todo_board": [f"pending: {t['content']}" for t in todos],
        "scope": "main",
    }


def _state(way: str, todos: list) -> dict:
    return {
        "build_way": way,
        "todos": todos,
        "assembled_context": _assembled(way, todos),
        "actor_messages": [],
    }


def _scaffold_text(path_rel: str) -> str:
    stem = Path(path_rel).stem
    return f"# {stem}\n\n（待填）\n"


# —— assembler 追加行 ——


def test_assembler_way4_without_scaffold_appends_framework_line(tmp_path):
    """way4 且首个交付物不存在 → system 末尾追加框架先行说明行（工厂形态）。"""
    docs = SharedDocs(tmp_path)
    node = make_assembler_node(shared_docs=docs)
    updates = node(_state("way4", WAY4_TODOS))
    assert SCAFFOLD_SUFFIX.strip() in updates["assembled_context"]["system"]


def test_assembler_way4_scaffold_exists_no_append(tmp_path):
    """框架已存在 → 不追加（首轮落框架后自然消失）。"""
    docs = SharedDocs(tmp_path)
    (tmp_path / "README.md").write_text("# README\n\n已有\n", encoding="utf-8")
    node = make_assembler_node(shared_docs=docs)
    updates = node(_state("way4", WAY4_TODOS))
    assert SCAFFOLD_SUFFIX.strip() not in updates["assembled_context"]["system"]


def test_graph_way4_first_round_lays_scaffold(tmp_path: Path):
    """way4 首轮：先落 6 份占位框架再走模型；assembler system 带追加行。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "澄清：需求范围从哪块开始？\n写入：README.md\n# README\n\n本项目是记账工具。（首轮只填一点）",
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-w4-scaf")
    seed = {
        "task_brief": "记账工具",
        "build_way": "way4",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "selected_proposal": 0,
        "todos": WAY4_TODOS,
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"

    # 6 份占位框架全部落盘（幂等：README 被本轮"写入："覆写为实际内容）
    for name in DELIVERABLE_SETS["way4"]:
        assert (tmp_path / name).exists(), f"{name} 未落盘"

    # 首轮的"写入："覆写了 README（占位框架 → 实际内容）
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert readme == "# README\n\n本项目是记账工具。（首轮只填一点）"

    # 其余文档仍是占位框架
    for name in DELIVERABLE_SETS["way4"][1:]:
        assert (tmp_path / name).read_text(encoding="utf-8") == _scaffold_text(name)

    # assembler system 带框架先行行（首文档存在后不再追加——但本轮装配时
    # 尚未落盘，故首轮命中追加）
    assert SCAFFOLD_SUFFIX in r1["assembled_context"]["system"]


def test_graph_way4_second_round_scaffold_line_gone_and_docs_grow(tmp_path: Path):
    """第二轮：框架已存在 → assembler 不再追加该行；文档内容增长（逐轮生长）。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "澄清：需求范围？\n写入：README.md\n# README\n\n首段。",
            "task_complete: false",
            "继续填需求。\n写入：README.md\n# README\n\n首段。第二段。",
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-w4-grow")
    seed = {
        "task_brief": "记账工具",
        "build_way": "way4",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "selected_proposal": 0,
        "todos": WAY4_TODOS,
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    readme1 = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert readme1 == "# README\n\n首段。"

    r2 = app.invoke({"actor_messages": [HumanMessage(content="继续")]}, cfg)
    readme2 = (tmp_path / "README.md").read_text(encoding="utf-8")
    # 逐轮生长：内容增长（非一次倾倒）
    assert readme2 == "# README\n\n首段。第二段。"
    assert len(readme2) > len(readme1)

    # 第二轮装配时框架已存在 → system 无追加行
    assert SCAFFOLD_SUFFIX not in r2["assembled_context"]["system"]


def test_graph_way3_assembler_no_scaffold_line(tmp_path: Path):
    """way3：不追加框架先行行（DocScaffold 为 way4 专属）。"""
    saver = InMemorySaver()
    model = ScriptedModel(["澄清：README 面向谁？", "task_complete: false"])
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-w3-noscaf")
    seed = {
        "task_brief": "x",
        "build_way": "way3",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "todos": [{"content": "编写 README", "status": "pending"}],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert SCAFFOLD_SUFFIX not in r1["assembled_context"]["system"]
    # way3 不落占位框架
    assert not (tmp_path / "README.md").exists()


# —— 占位框架幂等（单元级）——


def test_grilling_body_first_round_writes_scaffold_idempotent(tmp_path: Path):
    """首轮落框架；已存在文件跳过（幂等不覆写）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["澄清：范围？"])
    node = make_actor_node(model, shared_docs=docs)
    # round_count==1（state 无 round_count → 0+1=1）且 way4 → 落框架
    node(_state("way4", WAY4_TODOS), _cfg())
    for name in DELIVERABLE_SETS["way4"]:
        assert (tmp_path / name).read_text(encoding="utf-8") == _scaffold_text(name)

    # 已存在文件跳过：预写一个非占位内容的文件再跑首轮
    (tmp_path / "README.md").write_text("# 已有内容\n", encoding="utf-8")
    model2 = ScriptedModel(["澄清：范围？"])
    node2 = make_actor_node(model2, shared_docs=SharedDocs(tmp_path))
    node2(_state("way4", WAY4_TODOS), _cfg())
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# 已有内容\n"  # 不覆写


def test_grilling_body_non_first_round_no_scaffold(tmp_path: Path):
    """round_count>1：不落框架（仅首轮）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["继续填。"])
    node = make_actor_node(model, shared_docs=docs)
    node({**_state("way4", WAY4_TODOS), "round_count": 5}, _cfg())
    for name in DELIVERABLE_SETS["way4"]:
        assert not (tmp_path / name).exists()


def test_grilling_body_way3_first_round_no_scaffold(tmp_path: Path):
    """way3 首轮不落框架（DocScaffold way4 专属）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["澄清？"])
    node = make_actor_node(model, shared_docs=docs)
    node(_state("way3", [{"content": "编写 README", "status": "pending"}]), _cfg())
    assert not (tmp_path / "README.md").exists()


def test_grilling_body_no_shared_docs_no_scaffold():
    """shared_docs=None：不落框架（模型照常出牌）。"""
    model = ScriptedModel(["澄清？"])
    node = make_actor_node(model)
    updates = node(_state("way4", WAY4_TODOS), _cfg())
    assert updates["turn_end_reason"] == "round"


def test_scaffold_placeholder_text_shape():
    """占位框架文本形状：f"# {stem}\\n\\n（待填）\\n"。"""
    assert _scaffold_text("README.md") == "# README\n\n（待填）\n"
    assert _scaffold_text("docs/需求规格.md") == "# 需求规格\n\n（待填）\n"
