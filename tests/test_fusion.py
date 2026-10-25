"""统一输入协议：所有断点输入都是自由文本，按协议表融合进目标私有 key。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from project_agent.fusion import _PRIVATE_KEY_BY_ROLE, fusion_update
from project_agent.protocol import BREAKPOINT_PROTOCOL, Fusion, Role, TurnEndReason


def _fused_text(update: dict) -> tuple[str, str]:
    """返回 (融合目标 key, 文本)。"""
    assert len(update) == 1, f"融合更新应恰好指向一个私有 key，实际 {list(update)}"
    key, messages = next(iter(update.items()))
    assert len(messages) == 1
    msg = messages[0]
    assert isinstance(msg, HumanMessage)
    return key, str(msg.content)


def test_round_fuses_into_mainline():
    state = {"turn_end_reason": TurnEndReason.ROUND.value}
    key, text = _fused_text(fusion_update(state, "继续"))
    assert key == "actor_messages"
    assert text == "继续"


def test_question_fuses_into_asker_private_key():
    state = {
        "turn_end_reason": TurnEndReason.QUESTION.value,
        "awaiting_input_from": "demo",
    }
    key, _ = _fused_text(fusion_update(state, "选 B"))
    assert key == "demo_messages"


def test_question_with_unknown_role_falls_back_to_mainline():
    state = {
        "turn_end_reason": TurnEndReason.QUESTION.value,
        "awaiting_input_from": "someone-new",
    }
    key, _ = _fused_text(fusion_update(state, "答"))
    assert key == "actor_messages"


def test_question_without_asker_defaults_to_actor():
    state = {"turn_end_reason": TurnEndReason.QUESTION.value}
    key, _ = _fused_text(fusion_update(state, "答"))
    assert key == "actor_messages"


def test_resolution_reasons_feed_resolution_channel():
    """01 欠账 a：RESOLUTION 显式语义——输入经 resolution_inputs 通道送决议节点。"""


    for reason in (
        TurnEndReason.CHOICE_BUILD_WAY,
        TurnEndReason.CHOICE_PROPOSAL,
        TurnEndReason.DOCS_DONE,
    ):
        update = fusion_update({"turn_end_reason": reason.value}, "自由输入")
        assert update == {"resolution_inputs": ["自由输入"]}, reason
        assert BREAKPOINT_PROTOCOL[reason].fusion is Fusion.RESOLUTION


def test_loop_exhausted_still_fuses_into_mainline():
    key, _ = _fused_text(
        fusion_update({"turn_end_reason": TurnEndReason.LOOP_EXHAUSTED.value}, "自由输入")
    )
    assert key == "actor_messages"


def test_private_key_by_role_is_keyed_by_role_enum():
    """01 欠账 a：角色私有键以 Role 枚举为键（协议级类型收紧）。"""
    assert set(_PRIVATE_KEY_BY_ROLE) == {Role.ACTOR, Role.DEMO}
    assert _PRIVATE_KEY_BY_ROLE[Role.ACTOR] == "actor_messages"
    assert _PRIVATE_KEY_BY_ROLE[Role.DEMO] == "demo_messages"


def test_question_accepts_role_enum_as_asker():
    """REPL 侧 awaiting_input_from 写 Role 时同样命中私有 key。"""
    state = {
        "turn_end_reason": TurnEndReason.QUESTION.value,
        "awaiting_input_from": Role.DEMO.value,
    }
    key, _ = _fused_text(fusion_update(state, "答"))
    assert key == "demo_messages"


def test_finished_is_terminal_no_fusion():
    state = {"turn_end_reason": TurnEndReason.FINISHED.value}
    assert fusion_update(state, "还想说话") == {}


def test_unset_reason_defaults_to_mainline():
    key, _ = _fused_text(fusion_update({}, "第一句话"))
    assert key == "actor_messages"
