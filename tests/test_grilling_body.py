"""07 票：grilling 身体（way2-4）——与 way1 同构 + prompt 追加澄清行。

验收 2（切片 2 部分）：way2/3/4 会话回放各一条：ScriptedModel 出澄清问题
→"完成：…"→todos 勾选；prompt 末尾含 grilling 差异行。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import _ACTOR_BODIES, make_actor_node
from project_agent.routing import CONTEXT_ASSEMBLER, entry_route
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]

WAY4_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "搭建文档框架", "status": "pending"},
    {"content": "填写核心文档", "status": "pending"},
]

# 终裁 B：追加行文案（grilling 驱动核心）
GRILLING_SUFFIX = "请先提出一个澄清问题以推进构建（如已完成请输出：完成：{首个未清 todo 的 content}）。"


def _cfg(thread: str = "t-grill") -> dict:
    return {"configurable": {"thread_id": thread}}


def _assembled(way: str, todos: list) -> dict:
    return {
        "system": f"你是构建 agent。当前方式 {way}，指引 off，待办 {len(todos)} 项",
        "todo_board": [f"pending: {t['content']}" for t in todos],
        "scope": "main",
    }


def _state(way: str, todos: list, history: list | None = None) -> dict:
    return {
        "build_way": way,
        "todos": todos,
        "assembled_context": _assembled(way, todos),
        "actor_messages": history or [],
    }


# —— 身体表派生：way2-4 全部映射 grilling 身体 ——


def test_actor_bodies_way2_to_4_are_grilling_way1_is_react():
    """_ACTOR_BODIES：way1=react；way2/3/4 同一 grilling 身体函数。"""
    from project_agent.nodes import _grilling_body, _way1_actor_body

    assert _ACTOR_BODIES["way1"] is _way1_actor_body
    assert _ACTOR_BODIES["way2"] is _grilling_body
    assert _ACTOR_BODIES["way3"] is _grilling_body
    assert _ACTOR_BODIES["way4"] is _grilling_body


def test_unknown_way_body_falls_back_to_react():
    from project_agent.nodes import _way1_actor_body

    assert _ACTOR_BODIES.get("way9", _way1_actor_body) is _way1_actor_body


# —— grilling prompt 差异行 ——


@pytest.mark.parametrize("way", ["way2", "way3", "way4"], ids=["way2", "way3", "way4"])
def test_grilling_prompt_appends_clarification_line(way: str):
    """差异仅在 prompt 末尾追加 grilling 行——system 末尾含该行。"""
    model = ScriptedModel(["澄清：你想要什么数据存储？"])
    node = make_actor_node(model)
    node(_state(way, TWO_PENDING), _cfg())
    system = model.calls[0]["messages"][0]["content"]
    assert system.endswith("\n请先提出一个澄清问题以推进构建（如已完成请输出：完成：{首个未清 todo 的 content}）。")


def test_way1_prompt_has_no_grilling_line():
    """way1 身体不追加（既有行为零改动）。"""
    model = ScriptedModel(["回复"])
    node = make_actor_node(model)
    node(_state("way1", TWO_PENDING), _cfg())
    system = model.calls[0]["messages"][0]["content"]
    assert "请先提出一个澄清问题" not in system


def test_grilling_body_model_response_flows_full_pipeline(tmp_path):
    """模型响应照旧走 todos 勾选/记录桥/【R#】落盘/round_summary 全套（与 way1 同构）。"""
    from project_agent.shared_docs import SharedDocs

    text = "完成：梳理需求边界。记录：需求先做只读版"
    docs = SharedDocs(tmp_path)
    model = ScriptedModel([text])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(
        {**_state("way3", TWO_PENDING), "round_count": 0, "notes_version": 0},
        _cfg(),
    )
    assert updates["actor_messages"] == [AIMessage(content=text)]
    assert [item["status"] for item in updates["todos"]] == ["completed", "pending"]
    assert updates["round_count"] == 1
    assert docs.read_rounds() == [(1, f"【R1】{text}")]
    assert docs.notepad_entries() == [(1, "需求先做只读版")]
    assert updates["notes_version"] == 1
    assert updates["round_summary"] == text
    assert updates["turn_end_reason"] == "round"
    assert updates["turn_end_payload"]["round_output"] == text


# —— 图级回放：way2/way3 各一条（澄清→完成勾选）——


def test_graph_way2_grilling_replay(tmp_path):
    """way2 回放：R1 澄清问题（带记录桥）→ R2 完成勾选。【R#】逐轮落盘。"""

    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "澄清：目标用户是谁？\n记录：先定位单机用户",
            "task_complete: false",
            "完成：梳理需求边界",
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-way2")
    todos = [
        {"content": "梳理需求边界", "status": "pending"},
        {"content": "产出一页纸方案", "status": "pending"},
    ]
    seed = {
        "task_brief": "做个备忘工具",
        "build_way": "way2",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "todos": todos,
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"
    assert r1["round_count"] == 1
    assert "澄清" in r1["turn_end_payload"]["round_output"]
    assert [item["status"] for item in r1["todos"]] == ["pending", "pending"]

    r2 = app.invoke({"actor_messages": [HumanMessage(content="个人单机")]}, cfg)
    assert r2["round_count"] == 2
    assert [item["status"] for item in r2["todos"]] == ["completed", "pending"]

    # actor 调用 system 末尾带 grilling 行（两轮皆然）
    actor_calls = [c for c in model.calls if c["role"] == "actor"]
    assert len(actor_calls) == 2
    for call in actor_calls:
        assert call["messages"][0]["content"].endswith(GRILLING_SUFFIX)


def test_graph_way3_grilling_replay():
    """way3 回放：澄清→完成勾选；todos 为 way3 模板项。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "澄清：README 面向谁？\n记录：README 面向使用者",
            "task_complete: false",
            "完成：编写 README",
            "task_complete: true",
        ]
    )
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg("g-way3")
    todos = [
        {"content": "编写 README", "status": "pending"},
    ]
    seed = {
        "task_brief": "x",
        "build_way": "way3",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "todos": todos,
        "actor_messages": [HumanMessage(content="继续")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"
    # 第一轮：澄清问题，不勾选
    assert [item["status"] for item in r1["todos"]] == ["pending"]

    r2 = app.invoke({"actor_messages": [HumanMessage(content="面向使用者")]}, cfg)
    assert r2["turn_end_reason"] == "round"
    assert [item["status"] for item in r2["todos"]] == ["completed"]

    actor_calls = [c for c in model.calls if c["role"] == "actor"]
    assert actor_calls[0]["messages"][0]["content"].endswith(GRILLING_SUFFIX)


def test_graph_way4_grilling_replay_body_selected():
    """way4 回放：grilling 身体（prompt 差异行命中）。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            "澄清：需求规格的深度？",
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg("g-way4")
    seed = {
        "task_brief": "x",
        "build_way": "way4",
        "guidance_pref": "off",
        "guidance_mode": "off",
        "selected_proposal": 0,
        "todos": WAY4_PENDING,
        "actor_messages": [HumanMessage(content="推进")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "round"
    actor_calls = [c for c in model.calls if c["role"] == "actor"]
    assert actor_calls[0]["messages"][0]["content"].endswith(GRILLING_SUFFIX)


def test_entry_route_way4_with_todos_set_goes_to_assembler():
    """selected_proposal 已设 + todos 未清 → 主环（切片 5 前置：路由行不受影响）。"""
    assert (
        entry_route(
            {
                "task_brief": "x",
                "build_way": "way4",
                "guidance_pref": "auto",
                "selected_proposal": 1,
                "todos": WAY4_PENDING,
            }
        )
        == CONTEXT_ASSEMBLER
    )
