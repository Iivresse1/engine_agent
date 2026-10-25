"""两旋钮构造纪律：full/yolo 仅 flag 可达；决策模式映射；默认档。"""

from __future__ import annotations

import dataclasses

import pytest

from project_agent.tools.knobs import (
    Boundary,
    Interrupt,
    ShellKnobs,
    from_decision_mode,
)


def test_default_knobs_are_project_write_ai_review():
    k = ShellKnobs()
    assert k.boundary is Boundary.PROJECT_WRITE
    assert k.interrupt is Interrupt.AI_REVIEW


def test_full_requires_flag():
    with pytest.raises(ValueError):
        ShellKnobs(boundary=Boundary.FULL)
    k = ShellKnobs(boundary=Boundary.FULL, full_via_flag=True)
    assert k.boundary is Boundary.FULL


def test_yolo_requires_flag():
    with pytest.raises(ValueError):
        ShellKnobs(interrupt=Interrupt.YOLO)
    k = ShellKnobs(interrupt=Interrupt.YOLO, yolo_via_flag=True)
    assert k.interrupt is Interrupt.YOLO


def test_knobs_frozen():
    k = ShellKnobs()
    with pytest.raises(dataclasses.FrozenInstanceError):
        k.boundary = Boundary.FULL  # type: ignore[misc]


def test_from_decision_mode_english():
    assert from_decision_mode("ai_review").interrupt is Interrupt.AI_REVIEW
    assert from_decision_mode("human").interrupt is Interrupt.HUMAN


def test_from_decision_mode_chinese():
    assert from_decision_mode("AI 自动审核").interrupt is Interrupt.AI_REVIEW
    assert from_decision_mode("全权人工").interrupt is Interrupt.HUMAN


def test_from_decision_mode_maps_to_default_boundary():
    k = from_decision_mode("human")
    assert k.boundary is Boundary.PROJECT_WRITE


def test_from_decision_mode_yolo_raises():
    with pytest.raises(ValueError):
        from_decision_mode("yolo")


def test_from_decision_mode_unknown_raises():
    with pytest.raises(ValueError):
        from_decision_mode("turbo")
