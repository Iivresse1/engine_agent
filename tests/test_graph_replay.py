"""主接缝回放：invoke(融合更新) → 轮终 state；断点续跑零真模型。

02 起 build_ways 走 choice:build_way 断点 + 决议通道（resolution_inputs），
回放输入按 fusion_update 语义构造（无 reducer 整覆写：[*existing, text]）。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_build_ways_node

pytestmark = pytest.mark.replay


def _say(text: str) -> dict:
    return {"actor_messages": [HumanMessage(content=text)]}


def _resolve(state: dict, text: str) -> dict:
    """REPL 融合端语义：resolution_inputs 无 reducer，发送整列表。"""
    return {"resolution_inputs": [*(state.get("resolution_inputs") or []), text]}


def _cfg(thread: str = "t1") -> dict:
    return {"configurable": {"thread_id": thread}}


def test_three_round_breakpoint_replay():
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)

    # 首启问卷：问答四轮
    r1 = app.invoke(_say("我想做一个记账 CLI"), _cfg())
    assert r1["turn_end_reason"] == "question"  # Q1
    assert r1["turn_end_payload"]["question_text"] == "你的编程基础？"
    assert "task_brief" not in r1  # 首轮想法绝不被当答案
    r2 = app.invoke(_say("有一定编程基础"), _cfg())
    assert r2["user_mode"] == "experienced"
    assert r2["turn_end_reason"] == "question"  # Q2
    r3 = app.invoke(_say("自动每轮"), _cfg())
    assert r3["guidance_pref"] == "auto"
    r4 = app.invoke(_say("AI 自动审核"), _cfg())
    assert r4["decision_mode"] == "ai_review"
    r5 = app.invoke(_say("默认技能包"), _cfg())
    assert r5["skill_packs"] == ["default"]
    assert r5["task_brief"] == "我想做一个记账 CLI"  # 从首条人类消息写定
    assert r5["turn_end_reason"] == "round"

    r6 = app.invoke(_say("无关键词闲聊"), _cfg())
    assert r6["turn_end_reason"] == "choice:build_way"  # 首入 build_ways：发 choice 断点
    assert r6["turn_end_payload"]["options"] == ["对话", "轻 grill", "简化文档", "完整文档"]

    r7 = app.invoke(_resolve(r6, "用完整文档"), _cfg())
    assert r7["build_way"] == "way4"
    assert r7["task_brief"] == "我想做一个记账 CLI"  # 断点续跑：状态延续
    assert r7["turn_end_reason"] == "round"
    assert r7["resolution_inputs"] == []  # 决议后通道清空


def test_state_restored_across_app_instances():
    """END 后同 thread 再 invoke：从 START 重跑且 state 恢复（版本敏感行为实测）。"""
    saver = InMemorySaver()
    app1 = build_graph(checkpointer=saver)
    answers = ["我不了解编程", "自动每轮", "全权人工", "暂不启用"]
    state = app1.invoke(_say("原始想法"), _cfg())
    for text in answers:
        state = app1.invoke(_say(text), _cfg())
    assert state["task_brief"] == "原始想法"
    r_choice = app1.invoke(_say("轻方式"), _cfg())
    app1.invoke(_resolve(r_choice, "轻"), _cfg())

    app2 = build_graph(checkpointer=saver)
    r = app2.invoke(_say("继续"), _cfg())
    assert r["task_brief"] == "原始想法"
    assert r["build_way"] == "way2"
    assert "占位" in r["turn_end_payload"]["round_output"]  # 跳过 ask_tasks/build_ways


def test_full_onboarding_to_completion_replay():
    """大回放：idea→四问→简报→choice→决议→guidance→占位，逐轮断言。

    - 四问仅首次（后续轮零 question reason——choice 之后不再有问卷）
    - task_brief 恒定（写定后不被后续轮改写）
    - model 恰一次调用（choice 推荐；决议重发复用不重调）
    - 决议后通道清空
    """
    from tests.doubles.fake_model import ScriptedModel

    saver = InMemorySaver()
    model = ScriptedModel(["way3|简化起步快"])  # 仅 choice 推荐触一次
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg("full")

    # 首轮：idea → Q1
    r = app.invoke(_say("我想做个记账 CLI"), cfg)
    assert r["turn_end_reason"] == "question"
    assert "task_brief" not in r

    # 四问逐轮：答案解释落盘
    r = app.invoke(_say("我不了解编程"), cfg)
    assert r["user_mode"] == "novice"
    assert "新手推荐 1" in r["turn_end_payload"]["question_text"]  # Q2 带 hint
    r = app.invoke(_say("自动每轮"), cfg)
    assert r["guidance_pref"] == "auto"
    r = app.invoke(_say("AI 自动审核"), cfg)
    assert r["decision_mode"] == "ai_review"
    r = app.invoke(_say("默认技能包"), cfg)
    assert r["skill_packs"] == ["default"]
    assert r["task_brief"] == "我想做个记账 CLI"  # 从首条人类消息写定
    assert r["turn_end_reason"] == "round"
    brief = r["task_brief"]

    # choice 断点：model 恰一次调用
    r_choice = app.invoke(_say("嗯"), cfg)
    assert r_choice["turn_end_reason"] == "choice:build_way"
    assert len(model.calls) == 1
    assert r_choice["turn_end_payload"]["recommendation"] == "简化文档"
    assert r_choice["turn_end_payload"]["recommendation_reason"] == "简化起步快"

    # 决议：序号解释
    r = app.invoke(_resolve(r_choice, "1"), cfg)
    assert r["build_way"] == "way1"
    assert r["resolution_inputs"] == []
    assert r["guidance_mode"] == "off"  # way1 纯对话→off
    assert r["task_brief"] == brief  # 恒定
    assert len(model.calls) == 1  # 决议不重调 model

    # 后续轮：零 question reason（四问仅首次）
    r = app.invoke(_say("继续"), cfg)
    assert r["turn_end_reason"] == "round"
    assert "占位" in r["turn_end_payload"]["round_output"]
    assert r["task_brief"] == brief
    assert r["turn_end_reason"] != "question"
    assert len(model.calls) == 1


def test_guidance_mode_persists_across_app_instances():
    """guidance_mode 三态落盘：跨 app 实例持久化（novice+pref=auto）。"""
    saver = InMemorySaver()
    app1 = build_graph(checkpointer=saver)
    cfg = _cfg("gm")
    r = app1.invoke(
        {
            "task_brief": "想法",
            "user_mode": "novice",
            "guidance_pref": "auto",
            "decision_mode": "manual",
            "skill_packs": [],
            "resolution_inputs": ["3"],
        },
        cfg,
    )
    assert r["guidance_mode"] == "auto"

    app2 = build_graph(checkpointer=saver)
    r2 = app2.invoke(_say("继续"), cfg)
    assert r2["guidance_mode"] == "auto"
    assert r2["build_way"] == "way3"


def test_questionnaire_seeded_input_fast_forwards_to_build_ways():
    """seed 问卷字段直接入 invoke 输入：可快进到 build_ways 相位（01 遗留直达）。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    cfg = _cfg("seed")
    r = app.invoke(
        {
            "task_brief": "已有简报",
            "user_mode": "experienced",
            "guidance_pref": "ask",
            "decision_mode": "manual",
            "skill_packs": [],
            "resolution_inputs": [],
        },
        cfg,
    )
    assert r["turn_end_reason"] == "choice:build_way"  # 零 question 轮
    from project_agent.nodes import ask_tasks_node

    state = {"actor_messages": [HumanMessage("新文本")], "task_brief": "已定的简报"}
    updates = ask_tasks_node(state)
    assert "task_brief" not in updates  # 已有简报不被改写（可重入）


def test_build_ways_node_is_idempotent_on_reentry():
    state = {"actor_messages": [HumanMessage("完整文档")], "build_way": "way1"}
    updates = make_build_ways_node(None)(state)
    assert "build_way" not in updates  # 已定方式不被改写（可重入）


def test_uninterpretable_resolution_reshows_choice_not_stale():
    """解释不了的决议输入：清空通道并重发 choice（复用上轮 payload），零 model 调用。"""
    from tests.doubles.fake_model import ScriptedModel

    saver = InMemorySaver()
    model = ScriptedModel(["way3|理由"])  # 仅首次 choice 触模型
    app = build_graph(checkpointer=saver, model=model)

    answers = ["我不了解编程", "自动每轮", "全权人工", "暂不启用"]
    state = app.invoke(_say("我想做记账 CLI"), _cfg())
    for text in answers:
        state = app.invoke(_say(text), _cfg())
    r_choice = app.invoke(_say("嗯"), _cfg())
    assert len(model.calls) == 1
    r2 = app.invoke(_resolve(r_choice, "随便说什么都不含关键词"), _cfg())

    assert r2["turn_end_reason"] == "choice:build_way"
    assert r2["turn_end_payload"] == r_choice["turn_end_payload"]  # 复用重发
    assert r2["resolution_inputs"] == []
    assert len(model.calls) == 1  # 复用重发：零重复 ModelClient 调用


def test_round_payload_carries_todo_board():
    """spec 断点协议表 round 行：payload = 轮产出 + todo 板。"""
    from project_agent.nodes import ask_tasks_node

    state = {
        "actor_messages": [HumanMessage("新任务")],
        "user_mode": "novice",
        "guidance_pref": "auto",
        "decision_mode": "manual",
        "skill_packs": [],
        "todos": [
            {"content": "搭骨架", "status": "completed"},
            {"content": "写文档", "status": "in_progress"},
        ],
    }
    updates = ask_tasks_node(state)
    board = updates["turn_end_payload"]["todo_board"]
    assert board == ["completed: 搭骨架", "in_progress: 写文档"]


def test_breakpoint_persists_across_processes(tmp_path):
    """票 L11『turn_end 落盘可查』：sqlite checkpointer 跨进程续跑。"""
    from project_agent.graph import sqlite_checkpointer

    db = tmp_path / "state.db"

    with sqlite_checkpointer(db) as checkpointer:
        app = build_graph(checkpointer=checkpointer)
        state = app.invoke(_say("我想做一个记账 CLI"), _cfg("persist-t"))
        for text in ["我不了解编程", "自动每轮", "全权人工", "暂不启用"]:
            state = app.invoke(_say(text), _cfg("persist-t"))
        assert state["task_brief"] == "我想做一个记账 CLI"
        r_choice = app.invoke(_say("下一步"), _cfg("persist-t"))
        assert r_choice["turn_end_reason"] == "choice:build_way"

    # 进程退出后重开：新 app 实例、同一 sqlite 库、同 thread——状态恢复续跑
    with sqlite_checkpointer(db) as checkpointer:
        app2 = build_graph(checkpointer=checkpointer)
        r2 = app2.invoke(_resolve(r_choice, "简化文档"), _cfg("persist-t"))
        assert r2["task_brief"] == "我想做一个记账 CLI"
        assert r2["build_way"] == "way3"
