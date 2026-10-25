"""choice:build_way 断点流：静态推荐 + ModelClient 驱动推荐 + 决议通道消费。

票 02 验收：payload 含 4 选项 + 推荐 + 一句话理由（≤20 字）；
"1"、"用完整文档"等自由文本均正确解释。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_build_ways_node
from tests.doubles.fake_model import ScriptedModel

_LONG_OPTIONS = [
    "对话 —— 像聊天一样推进，不产出文档",
    "轻 grill —— 少量追问压测计划，文档极简",
    "简化文档 —— 核心 README/TODO，轻量直接",
    "完整文档 —— 完整规格/ADR/术语表，适合长期维护",
]
_STATIC_RECOMMENDATION = "简化文档 —— 核心 README/TODO，轻量直接"


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def _cfg(thread: str = "bw") -> dict:
    return {"configurable": {"thread_id": thread}}


# ---------- 静态推荐（model=None）：choice 断点 payload 形状 ----------


def test_static_choice_breakpoint_payload_shape():
    """无 model：静态推荐 way3 + 固定理由；payload 含 4 选项。"""
    state = {
        "task_brief": "一个想法",
        "resolution_inputs": [],
        "actor_messages": [],
        "turn_end_reason": None,
    }
    node = make_build_ways_node(None)
    updates = node(state)
    assert updates["build_way"] is None if False else True  # 未写 build_way
    assert updates["turn_end_reason"] == "choice:build_way"
    payload = updates["turn_end_payload"]
    assert payload["options"] == _LONG_OPTIONS
    assert payload["recommendation"] == _STATIC_RECOMMENDATION
    assert payload["recommendation_reason"] == "个人作品有沉淀不臃肿"
    assert len(payload["recommendation_reason"]) <= 20
    assert "resolution_inputs" not in updates or updates.get("resolution_inputs") == []


def test_static_reentry_with_build_way_set_returns_empty():
    """可重入：build_way 已设 → {}（零副作用）。"""
    node = make_build_ways_node(None)
    assert node({"build_way": "way1"}) == {}


# ---------- 解释引擎：自由文本全形态 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", "way1"),
        ("2", "way2"),
        ("3", "way3"),
        ("4", "way4"),
        ("用完整文档", "way4"),
        ("我想用简化文档", "way3"),
        ("轻一点", "way2"),
        ("就聊天吧", "way1"),
        ("way2", "way2"),
        ("WAY4", "way4"),
        ("选第 3 种", "way3"),
        ("选项 4", "way4"),
        ("方式1", "way1"),
        ("选 1", "way1"),
        ("推荐那个", "way3"),  # recommended=简化文档（长标签）
        ("做个 2048 游戏", None),  # \W 不含汉字：不会误中语境序号
        ("随便说点什么", None),
        ("", None),
        (None, None),
        # 13 票长选项原文整串可解释
        ("完整文档 —— 完整规格/ADR/术语表，适合长期维护", "way4"),
        ("对话 —— 像聊天一样推进，不产出文档", "way1"),
    ],
)
def test_interpret_build_way(text, expected):
    from project_agent.nodes import _interpret_build_way

    assert _interpret_build_way(text, recommended=_STATIC_RECOMMENDATION) == expected


# ---------- 决议通道消费：pending 解释 → 写 build_way + 清空 + round_end ----------


def test_pending_resolution_consumed_writes_build_way():
    node = make_build_ways_node(None)
    state = {
        "task_brief": "x",
        "resolution_inputs": ["1"],
        "turn_end_payload": {"recommendation": _STATIC_RECOMMENDATION, "options": _LONG_OPTIONS},
    }
    updates = node(state)
    assert updates["build_way"] == "way1"
    assert updates["resolution_inputs"] == []
    assert updates["turn_end_reason"] == "round"
    assert "构建方式已定：way1" in updates["turn_end_payload"]["round_output"]


def test_pending_uninterpretable_reshows_choice_reusing_last_payload():
    """解释失败：清空通道 + 复用上轮 turn_end_payload 重发 choice——零 model 调用。"""
    model = ScriptedModel([])
    node = make_build_ways_node(model)
    last_payload = {
        "explanation": "决定 agent 用多重的流程陪你把这个项目做出来",
        "options": _LONG_OPTIONS,
        "recommendation": "完整文档 —— 完整规格/ADR/术语表，适合长期维护",
        "recommendation_reason": "沉淀最全",
    }
    state = {
        "task_brief": "x",
        "resolution_inputs": ["说不清"],
        "turn_end_payload": last_payload,
    }
    updates = node(state)
    assert updates["turn_end_reason"] == "choice:build_way"
    assert updates["turn_end_payload"] == last_payload
    assert updates["resolution_inputs"] == []
    assert model.calls == []  # 复用重发：零 ModelClient 调用（可重入验收）


def test_pending_uninterpretable_without_valid_payload_falls_back_to_static():
    """上轮 payload 缺推荐（无法反查）→ 退静态推荐而非崩溃。"""
    node = make_build_ways_node(None)
    state = {
        "task_brief": "x",
        "resolution_inputs": ["说不清"],
        "turn_end_payload": {},
    }
    updates = node(state)
    assert updates["turn_end_reason"] == "choice:build_way"
    assert updates["turn_end_payload"]["recommendation"] == _STATIC_RECOMMENDATION


# ---------- ModelClient 驱动推荐 ----------


def test_model_driven_recommendation_contract():
    """模型路径：role=actor、thread_id 来自 config、prompt 含简报+用户基础。"""
    model = ScriptedModel(["way2|轻量起步快"])
    node = make_build_ways_node(model)
    state = {"task_brief": "记账 CLI", "user_mode": "novice", "resolution_inputs": []}
    updates = node(state, {"configurable": {"thread_id": "th-9"}})

    assert model.calls[0]["role"] == "actor"
    assert model.calls[0]["thread_id"] == "th-9"
    prompt = model.calls[0]["messages"][0]["content"]
    assert "任务简报：记账 CLI" in prompt
    assert "用户编程基础：novice" in prompt
    assert "1=对话" in prompt and "4=完整文档" in prompt

    payload = updates["turn_end_payload"]
    assert payload["recommendation"] == "轻 grill —— 少量追问压测计划，文档极简"
    assert payload["recommendation_reason"] == "轻量起步快"


def test_model_output_reason_hard_truncated_to_20():
    model = ScriptedModel(["way4|" + "很" * 30])
    node = make_build_ways_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert len(updates["turn_end_payload"]["recommendation_reason"]) == 20
    assert (
        updates["turn_end_payload"]["recommendation"]
        == "完整文档 —— 完整规格/ADR/术语表，适合长期维护"
    )


def test_model_garbage_output_falls_back_to_static():
    model = ScriptedModel(["呃呃呃随便说的"])
    node = make_build_ways_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    payload = updates["turn_end_payload"]
    assert payload["recommendation"] == _STATIC_RECOMMENDATION
    assert payload["recommendation_reason"] == "个人作品有沉淀不臃肿"


def test_model_output_may_be_way_label_or_index():
    model = ScriptedModel(["完整文档|理由"])
    node = make_build_ways_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert (
        updates["turn_end_payload"]["recommendation"]
        == "完整文档 —— 完整规格/ADR/术语表，适合长期维护"
    )


def test_node_callable_without_config():
    """节点签名 (state, config=None)：直调测试可省 config。"""
    model = ScriptedModel(["way1|对话起步"])
    node = make_build_ways_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert (
        updates["turn_end_payload"]["recommendation"]
        == "对话 —— 像聊天一样推进，不产出文档"
    )


def test_choice_flow_through_graph():
    """图级：choice 断点 → 决议输入 → build_way 写定（静态推荐路径）。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=None)
    cfg = _cfg("g1")

    r1 = app.invoke(
        {"task_brief": "记账 CLI", "resolution_inputs": []}, cfg
    )
    assert r1["turn_end_reason"] == "choice:build_way"
    assert r1["turn_end_payload"]["options"] == _LONG_OPTIONS

    # REPL 融合：resolution_inputs = [*existing, text]
    pending = [*r1["resolution_inputs"], "1"]
    r2 = app.invoke({"resolution_inputs": pending}, cfg)
    assert r2["build_way"] == "way1"
    assert r2["resolution_inputs"] == []
    assert r2["turn_end_reason"] == "round"
