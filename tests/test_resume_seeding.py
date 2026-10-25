"""跨进程续跑断点回灌：choice 断点首答不丢（回归：真模型接线冒烟发现）。

复现路径：新 ReplHost（last_state 空）接续 choice:build_way 断点的
同 thread —— 修复前 fusion 把首答当 reason=None 融主线，决议通道
拿不到，choice 原样重发、build_way 永不置位。
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph, new_thread_id
from project_agent.repl import ReplHost
from tests.doubles.scripted_io import ScriptedIO

pytestmark = pytest.mark.replay


def _drive_to_choice_breakpoint(app, thread_id) -> None:
    """推会话到 choice:build_way 断点：首条进图（简报写定）+ 触发 choice。"""
    io = ScriptedIO(
        [
            "我想做一个记账 CLI",  # 首条自由文本 → 简报写定（14 票）
            "嗯",  # 触发 build_ways → choice 断点
            "/exit",
        ]
    )
    ReplHost(app, io, thread_id).run()
    out = "\n".join(io.outputs)
    assert "断点 · choice:build_way" in out


def test_choice_answer_survives_process_restart():
    """新宿主（同 thread、last_state 空）首答 choice：决议生效。"""
    app = build_graph(checkpointer=InMemorySaver())
    thread_id = new_thread_id()
    _drive_to_choice_breakpoint(app, thread_id)

    # "重启"：全新 ReplHost——run() 须从 checkpointer 回灌末态
    io = ScriptedIO(["对话", "需要", "/status", "/exit"])
    ReplHost(app, io, thread_id).run()
    out = "\n".join(io.outputs)
    assert "build_way: way1" in out  # 决议生效，非 choice 重发
    assert "断点 · choice:build_way" not in out
    # 决议同轮指引一问 → 答案落盘（guidance_pref/user_mode）
    assert "guidance_pref: auto" in out
    assert "user_mode: novice" in out


def test_stub_app_without_get_state_skips_seeding():
    """桩 app 无 get_state：跳过回灌零异常（旧测试形态兼容）。"""

    class StubApp:
        def invoke(self, update, config):
            return {"turn_end_reason": "round", "turn_end_payload": {}}

    io = ScriptedIO(["hello", "/exit"])
    ReplHost(StubApp(), io, new_thread_id()).run()
    assert "断点 · round" in "\n".join(io.outputs)


def test_fresh_thread_seeding_is_noop():
    """新 thread（checkpointer 无值）：回灌为空跳过，行为不变。"""
    app = build_graph(checkpointer=InMemorySaver())
    io = ScriptedIO(["我想做个工具", "/exit"])
    ReplHost(app, io, new_thread_id()).run()
    out = "\n".join(io.outputs)
    # 14 票：首条自由文本 → 简报写定（round 断点）
    assert "断点 · round" in out
    assert "任务简报已记录：我想做个工具" in out
