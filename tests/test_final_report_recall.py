"""12 票检索注入接线（v2.4）：finalizer 写 → 新会话 ask_tasks 读。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from project_agent.memory_store import InMemoryStore
from project_agent.nodes import make_ask_tasks_node


def _state(brief: str = "") -> dict:
    return {
        "task_brief": brief,
        "actor_messages": [HumanMessage(content="我想做一个记账 CLI")],
    }


def test_recall_injects_historical_final_report() -> None:
    """跨会话长期记忆的注入点：同 brief 的历史经验进简报回执。"""
    store = InMemoryStore()
    store.put("final_report:我想做一个记账 CLI", "上次栽在浮点精度，用整数分记账")
    node = make_ask_tasks_node(store=store)
    updates = node(_state(), None)
    payload = updates["turn_end_payload"]["round_output"]
    assert "任务简报已记录：我想做一个记账 CLI" in payload
    assert "历史经验（上次同类项目）" in payload
    assert "浮点精度" in payload


def test_recall_truncates_long_report() -> None:
    store = InMemoryStore()
    store.put("final_report:我想做一个记账 CLI", "甲" * 500)
    node = make_ask_tasks_node(store=store)
    payload = node(_state(), None)["turn_end_payload"]["round_output"]
    # 只截取前 80 字（不把整份报告灌进断点）
    assert payload.count("甲") == 80


def test_no_store_keeps_plain_brief_message() -> None:
    """无 store → 行为与 14 票逐字一致。"""
    node = make_ask_tasks_node()
    payload = node(_state(), None)["turn_end_payload"]["round_output"]
    assert payload == "任务简报已记录：我想做一个记账 CLI"


def test_store_miss_keeps_plain_message() -> None:
    store = InMemoryStore()
    store.put("final_report:别的项目", "无关经验")
    node = make_ask_tasks_node(store=store)
    payload = node(_state(), None)["turn_end_payload"]["round_output"]
    assert payload == "任务简报已记录：我想做一个记账 CLI"


def test_store_error_does_not_block_brief() -> None:
    """检索异常不阻断简报写定（fail-open 到既有行为）。"""

    class _BoomStore:
        def get(self, key):
            raise OSError("store 挂了")

    node = make_ask_tasks_node(store=_BoomStore())
    updates = node(_state(), None)
    assert updates["task_brief"] == "我想做一个记账 CLI"


def test_brief_already_set_is_noop() -> None:
    store = InMemoryStore()
    store.put("final_report:已有简报", "经验")
    node = make_ask_tasks_node(store=store)
    assert node(_state("已有简报"), None) == {}


def test_no_human_message_is_noop() -> None:
    node = make_ask_tasks_node(store=InMemoryStore())
    assert node({"task_brief": "", "actor_messages": []}, None) == {}


def test_finalizer_write_and_ask_tasks_read_share_key() -> None:
    """写入侧与检索侧 key 必须同源（否则检索永不命中）。"""
    import inspect

    from project_agent import nodes

    finalizer_source = inspect.getsource(nodes.make_finalizer_node)
    ask_source = inspect.getsource(nodes._recall_final_report)
    assert "final_report:" in finalizer_source
    assert "final_report:" in ask_source
    assert inspect.getsource(nodes.make_actor_node)  # 冒烟：模块可正常取源
