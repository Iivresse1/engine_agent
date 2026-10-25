"""guidance_trigger 节点：纯配置映射写 guidance_mode 三态（spec 节点表）。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import guidance_trigger_node
from project_agent.routing import GUIDANCE_TRIGGER


def test_guidance_trigger_node_writes_guidance_mode_only():
    """spec 节点表：只写 guidance_mode，不写 turn_end。"""
    state = {"build_way": "way2", "guidance_pref": "ask", "user_mode": "novice"}
    updates = guidance_trigger_node(state)
    assert updates == {"guidance_mode": "ask"}


def test_guidance_trigger_node_way1_off():
    updates = guidance_trigger_node(
        {"build_way": "way1", "guidance_pref": "auto", "user_mode": "novice"}
    )
    assert updates == {"guidance_mode": "off"}


def test_guidance_trigger_node_defaults_off():
    assert guidance_trigger_node({}) == {"guidance_mode": "off"}


def test_guidance_trigger_constant_wired():
    assert GUIDANCE_TRIGGER == "guidance_trigger"


def test_graph_routes_build_ways_to_guidance_trigger():
    """build_way 写定后：build_ways → guidance_trigger → END（guidance_mode 落盘）。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "gt1"}}

    r = app.invoke(
        {
            "task_brief": "想法",
            "resolution_inputs": ["用完整文档"],
        },
        cfg,
    )
    assert r["build_way"] == "way4"
    assert r["guidance_mode"] == "off"  # way4+pref 未设+非 novice → off
    assert r["turn_end_reason"] == "round"  # guidance_trigger 不产断点，round_end 由决议轮写
    # 可重入：再进一轮不再改 guidance_mode（build_way 已设直接 END）
    r2 = app.invoke({"actor_messages": []}, cfg)
    assert r2["guidance_mode"] == "off"


def test_graph_guidance_mode_via_preferences():
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "gt2"}}

    r = app.invoke(
        {
            "task_brief": "想法",
            "user_mode": "novice",
            "guidance_pref": "auto",
            "decision_mode": "manual",
            "skill_packs": [],
            "resolution_inputs": ["2"],
        },
        cfg,
    )
    assert r["build_way"] == "way2"
    assert r["guidance_mode"] == "auto"  # pref 优先
