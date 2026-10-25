"""07 票切片 3：SharedDocs.write_deliverable + "写入："解析 + 白名单。

- write_deliverable(path_rel, content)：root/path_rel 写 UTF-8、父目录 mkdir、
  白名单校验（文件名 ∈ DELIVERABLE_SETS[way]，不在→跳过）
- grilling 身体：响应含 "写入：{文件名}\\n{多行内容}" 模式 → 落盘交付物
- way1 不解析写入（零"写入："解析）
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.deliverables import DELIVERABLE_SETS
from project_agent.graph import build_graph
from project_agent.nodes import _parse_writes, make_actor_node
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]


def _cfg(thread: str = "t-wd") -> dict:
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


# —— SharedDocs.write_deliverable：基础写入 ——


def test_write_deliverable_writes_utf8_and_makes_parents(tmp_path):
    docs = SharedDocs(tmp_path)
    docs.write_deliverable("docs/需求规格.md", "# 需求\n\n（待填）\n", way="way4")
    target = tmp_path / "docs" / "需求规格.md"
    assert target.read_text(encoding="utf-8") == "# 需求\n\n（待填）\n"


def test_write_deliverable_top_level_file(tmp_path):
    docs = SharedDocs(tmp_path)
    docs.write_deliverable("README.md", "# 项目\n", way="way3")
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# 项目\n"


# —— 白名单校验 ——


@pytest.mark.parametrize(
    ("way", "path_rel", "allowed"),
    [
        ("way2", "IDEA.md", True),
        ("way2", "README.md", False),
        ("way3", "README.md", True),
        ("way3", "TODO.md", True),
        ("way3", "目录树.txt", True),
        ("way3", "IDEA.md", False),
        ("way3", "docs/需求规格.md", False),
        ("way4", "docs/需求规格.md", True),
        ("way4", "docs/技术选型.md", True),
        ("way4", "docs/目录结构.md", True),
        ("way4", "SECRET.md", False),
        ("way9", "README.md", False),
    ],
    ids=[
        "w2-idea-ok",
        "w2-readme-no",
        "w3-readme-ok",
        "w3-todo-ok",
        "w3-tree-ok",
        "w3-idea-no",
        "w3-docs-no",
        "w4-req-ok",
        "w4-tech-ok",
        "w4-struct-ok",
        "w4-secret-no",
        "unknown-way-no",
    ],
)
def test_write_deliverable_whitelist(tmp_path, way, path_rel, allowed):
    """文件名 ∈ DELIVERABLE_SETS[way] 白名单；不在→跳过（零写入零异常）。"""
    docs = SharedDocs(tmp_path)
    docs.write_deliverable(path_rel, "内容", way=way)
    exists = (tmp_path / path_rel).exists()
    assert exists is allowed


def test_write_deliverable_return_value_signals_skip(tmp_path):
    """跳过时可观察：返回 False（白名单拒绝），成功 True。"""
    docs = SharedDocs(tmp_path)
    assert docs.write_deliverable("README.md", "x", way="way3") is True
    assert docs.write_deliverable("HACK.md", "x", way="way3") is False


# —— "写入："解析（纯函数表驱动）——


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 单条：首行文件名，其后内容到段尾（strip 尾空白）
        (
            "先说两句\n写入：README.md\n# 标题\n\n正文",
            [("README.md", "# 标题\n\n正文")],
        ),
        # 多段：按 "\n写入：" 分段
        (
            "写入：README.md\n# R\n写入：TODO.md\n- [ ] 甲",
            [("README.md", "# R"), ("TODO.md", "- [ ] 甲")],
        ),
        # 段尾空白 strip
        (
            "写入：IDEA.md\n# 想法\n\n\n",
            [("IDEA.md", "# 想法")],
        ),
        # 无 "写入：" → 空
        ("普通回复，没有指令", []),
        # "写入：" 不在行首（中段粘连）→ 不解析（模式为行首）
        ("先写入：README.md\n内容", []),
    ],
    ids=["single", "two-segments", "trailing-strip", "none", "mid-line-ignored"],
)
def test_parse_writes_table_driven(text, expected):
    assert _parse_writes(text) == expected


def test_parse_writes_empty_and_none():
    assert _parse_writes("") == []
    assert _parse_writes("写入：") == []  # 空文件名段不产条目


# —— grilling 身体落盘：way3 会话回放 ——


def test_graph_way3_replay_writes_deliverables(tmp_path):
    """way3 回放：模型出"写入：README.md\n…"→ 三份交付物落盘带内容；【R#】照落 BUILD_LOG。"""
    r1_text = (
        "本轮先写 README。\n"
        "写入：README.md\n"
        "# 记账工具\n\n轻量记账。\n"
        "写入：TODO.md\n"
        "- [ ] 记账核心\n- [ ] 导出\n"
        "写入：目录树.txt\n"
        "src/\nREADME.md\n"
    )
    saver = InMemorySaver()
    model = ScriptedModel([r1_text, "task_complete: false"])
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-w3-writes")
    seed = {
        "task_brief": "记账工具",
        "build_way": "way3",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "todos": [
            {"content": "编写 README", "status": "pending"},
            {"content": "编写 TODO", "status": "pending"},
        ],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"
    # 三份交付物带内容落盘（白名单内全过）
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# 记账工具\n\n轻量记账。"
    assert (tmp_path / "TODO.md").read_text(encoding="utf-8") == "- [ ] 记账核心\n- [ ] 导出"
    assert (tmp_path / "目录树.txt").read_text(encoding="utf-8") == "src/\nREADME.md"
    # 模型全文（含写入指令）照旧入 BUILD_LOG 带【R#】
    assert r1["round_count"] == 1
    build_log = (tmp_path / "BUILD_LOG.md").read_text(encoding="utf-8")
    assert build_log.startswith("【R1】本轮先写 README。")


def test_graph_way3_whitelist_rejected_write_skipped(tmp_path):
    """白名单外文件名（way3 写 docs/需求规格.md）→ 跳过落盘；round_end 提示。"""
    r1_text = "尝试越界。\n写入：docs/需求规格.md\n# 需求\n"
    saver = InMemorySaver()
    model = ScriptedModel([r1_text, "task_complete: false"])
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-w3-reject")
    seed = {
        "task_brief": "x",
        "build_way": "way3",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "todos": [{"content": "编写 README", "status": "pending"}],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"
    assert not (tmp_path / "docs").exists()  # 越界零落盘
    # round_end 提示：payload round_output 追加提示行
    assert "白名单" in r1["turn_end_payload"]["round_output"]


def test_graph_way1_replay_zero_write_parsing(tmp_path):
    """way1 回放：响应即使含"写入："也不解析（零交付物落盘）。"""
    r1_text = "写入：README.md\n# 不该出现\n"
    saver = InMemorySaver()
    model = ScriptedModel([r1_text, "task_complete: false"])
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-w1-zero")
    seed = {
        "task_brief": "x",
        "build_way": "way1",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "todos": TWO_PENDING,
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"
    assert not (tmp_path / "README.md").exists()  # way1 零解析
    # BUILD_LOG 照落（写入指令是模型全文一部分）
    assert (tmp_path / "BUILD_LOG.md").read_text(encoding="utf-8").startswith("【R1】写入：")


def test_graph_way2_write_idea_only(tmp_path):
    """way2：IDEA.md 在白名单内落盘；README.md 越界跳过。"""
    r1_text = "写入：IDEA.md\n# 想法\n轻量方案。\n写入：README.md\n# 越界\n"
    saver = InMemorySaver()
    model = ScriptedModel([r1_text, "task_complete: false"])
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-w2-write")
    seed = {
        "task_brief": "x",
        "build_way": "way2",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "todos": [{"content": "产出一页纸方案", "status": "pending"}],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"
    assert (tmp_path / "IDEA.md").read_text(encoding="utf-8") == "# 想法\n轻量方案。"
    assert not (tmp_path / "README.md").exists()


def test_actor_shared_docs_none_still_no_write_parsing():
    """shared_docs=None：grilling 身体不落盘（与 06 行为一致），模型照常出牌。"""
    model = ScriptedModel(["写入：README.md\n# x\n"])
    node = make_actor_node(model)  # 无 shared_docs
    updates = node(_state("way3", TWO_PENDING), _cfg())
    assert updates["turn_end_reason"] == "round"
    assert updates["actor_messages"] == [AIMessage(content="写入：README.md\n# x\n")]


def test_way4_write_docs_deliverable(tmp_path):
    """way4：docs/ 子目录交付物可写（父目录 mkdir）。"""
    docs = SharedDocs(tmp_path)
    r = docs.write_deliverable("docs/技术选型.md", "# 选型\nPython。\n", way="way4")
    assert r is True
    assert (tmp_path / "docs" / "技术选型.md").read_text(encoding="utf-8") == "# 选型\nPython。\n"


def test_write_deliverable_full_whitelist_table(tmp_path):
    """表驱动全清单：DELIVERABLE_SETS 各 way 的每个文件名都可写。"""
    docs = SharedDocs(tmp_path)
    for way, filenames in DELIVERABLE_SETS.items():
        for name in filenames:
            assert docs.write_deliverable(name, f"# {name}\n", way=way) is True
            assert (tmp_path / name).exists()
