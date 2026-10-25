"""07 票切片 6：planner selected_proposal 深化首项（验收 5）+ way4 全链回放。

- way4 且 selected_proposal 已设 → todos 模板首项改为
  f"深化方案：{proposal_set[idx] 摘要}"（超过 40 字截断）；其余方式照旧模板
- way4 全链回放：提案 → 选定 → 深化 todos → grilling
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import planner_node
from tests.doubles.fake_model import ScriptedModel

LONG_PROPOSAL = "完整方案：" + "企业级" * 30  # 60+ 字：截断到 40


def _resolve(state: dict, text: str) -> dict:
    return {"resolution_inputs": [*(state.get("resolution_inputs") or []), text]}


# —— planner 深化首项 ——


def test_planner_way4_with_selected_proposal_deepens_first_item():
    """way4 + selected_proposal → 首项 = "深化方案：{proposal_set[idx]}"。"""
    proposals = ["轻量|快", "均衡|中", "完整|全"]
    state = {
        "task_brief": "x",
        "build_way": "way4",
        "selected_proposal": 1,
        "proposal_set": proposals,
        "todos": [],
    }
    updates = planner_node(state)
    contents = [item["content"] for item in updates["todos"]]
    assert contents[0] == "深化方案：均衡|中"
    # 其余项照 way4 模板（去掉首项"梳理需求边界"被深化替代）
    assert contents[1:] == ["搭建文档框架", "填写核心文档"]
    assert all(item["status"] == "pending" for item in updates["todos"])


def test_planner_way4_selected_proposal_truncates_to_40():
    """摘要超过 40 字 → 截断（"深化方案："前缀 + 40 字内的方案文本）。"""
    state = {
        "task_brief": "x",
        "build_way": "way4",
        "selected_proposal": 0,
        "proposal_set": [LONG_PROPOSAL],
        "todos": [],
    }
    updates = planner_node(state)
    first = updates["todos"][0]["content"]
    assert first.startswith("深化方案：")
    summary = first[len("深化方案："):]
    assert len(summary) == 40
    assert summary == LONG_PROPOSAL[:40]


def test_planner_way4_without_selected_proposal_uses_default_template():
    """way4 未选方案 → 照旧模板（首项"梳理需求边界"）。"""
    updates = planner_node({"task_brief": "x", "build_way": "way4", "todos": []})
    contents = [item["content"] for item in updates["todos"]]
    assert contents == ["梳理需求边界", "搭建文档框架", "填写核心文档"]


@pytest.mark.parametrize("way", ["way1", "way2", "way3"], ids=["w1", "w2", "w3"])
def test_planner_other_ways_ignore_selected_proposal(way):
    """非 way4：即使 selected_proposal 意外存在也不深化（照旧模板）。"""
    state = {
        "task_brief": "x",
        "build_way": way,
        "selected_proposal": 0,
        "proposal_set": ["轻量|快", "均衡|中", "完整|全"],
        "todos": [],
    }
    updates = planner_node(state)
    contents = [item["content"] for item in updates["todos"]]
    assert contents[0] != "深化方案：轻量|快"
    assert not contents[0].startswith("深化方案：")


def test_planner_way4_selected_with_empty_proposal_set_defensive():
    """selected_proposal 已设但 proposal_set 空/越界 → 防御照旧模板。"""
    state = {
        "task_brief": "x",
        "build_way": "way4",
        "selected_proposal": 5,
        "proposal_set": ["仅一案"],
        "todos": [],
    }
    updates = planner_node(state)
    contents = [item["content"] for item in updates["todos"]]
    assert contents == ["梳理需求边界", "搭建文档框架", "填写核心文档"]


# —— way4 全链回放：提案 → 选定 → 深化 todos → grilling ——


def test_way4_full_chain_replay(tmp_path):
    """全链：PROPOSALS 提案 → choice:proposal → 选定 → planner 深化首项 →
    grilling 工作轮（框架先行 + 写入）。"""
    from project_agent.deliverables import DELIVERABLE_SETS

    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "轻量工具|单文件起步\n均衡工具|包管理\n完整平台|服务化",  # 提案
            "完成：深化方案：轻量工具|单文件起步\n写入：README.md\n# README\n\n首版。\n",  # 工作轮
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = {"configurable": {"thread_id": "w4-full"}}

    # 1) 提案轮
    r1 = app.invoke(
        {
            "task_brief": "记账工具",
            "build_way": "way4",
            "guidance_pref": "off",
            "guidance_mode": "off",
            "todos": [],
            "actor_messages": [HumanMessage(content="开始")],
        },
        cfg,
    )
    assert r1["turn_end_reason"] == "choice:proposal"
    assert r1["proposal_set"] == [
        "轻量工具|单文件起步",
        "均衡工具|包管理",
        "完整平台|服务化",
    ]

    # 2) 选定（序号 1）
    r2 = app.invoke(_resolve(r1, "1"), cfg)
    assert r2["selected_proposal"] == 0
    assert r2["turn_end_reason"] == "round"

    # 3) planner 深化首项
    r3 = app.invoke({"actor_messages": [HumanMessage(content="继续")]}, cfg)
    assert r3["turn_end_reason"] == "round"
    contents = [item["content"] for item in r3["todos"]]
    assert contents[0] == "深化方案：轻量工具|单文件起步"
    assert contents[1:] == ["搭建文档框架", "填写核心文档"]

    # 4) grilling 工作轮：框架先行 + "写入：" + todos 勾选
    r4 = app.invoke({"actor_messages": [HumanMessage(content="开工")]}, cfg)
    assert r4["turn_end_reason"] == "round"
    assert [item["status"] for item in r4["todos"]] == ["completed", "pending", "pending"]
    # 6 份占位框架落盘 + README 被写入覆写
    for name in DELIVERABLE_SETS["way4"]:
        assert (tmp_path / name).exists()
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# README\n\n首版。"
    # BUILD_LOG 带【R1】
    assert (tmp_path / "BUILD_LOG.md").read_text(encoding="utf-8").startswith("【R1】")


def test_way4_full_chain_keyword_selection_deepens(tmp_path):
    """关键词选定（"均衡"）→ 深化首项取 proposal_set[1]。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "轻量工具|单文件\n均衡工具|包管理\n完整平台|服务化",
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = {"configurable": {"thread_id": "w4-kw"}}

    r1 = app.invoke(
        {
            "task_brief": "x",
            "build_way": "way4",
            "guidance_pref": "off",
            "todos": [],
            "actor_messages": [HumanMessage(content="开始")],
        },
        cfg,
    )
    r2 = app.invoke(_resolve(r1, "均衡"), cfg)
    assert r2["selected_proposal"] == 1

    r3 = app.invoke({"actor_messages": [HumanMessage(content="继续")]}, cfg)
    contents = [item["content"] for item in r3["todos"]]
    assert contents[0] == "深化方案：均衡工具|包管理"
