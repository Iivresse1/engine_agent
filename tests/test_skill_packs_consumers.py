"""17 票：skill_packs 的图内消费者（包两级 + falsy 陷阱第四处落点）。"""

from __future__ import annotations

import pathlib

from project_agent.skills import (
    DEFAULT_PACK,
    SKILLS,
    known_packs,
    skill_body,
    skill_heads,
)


def test_default_pack_contains_all_builtin_skills() -> None:
    names = {head.name for head in skill_heads([DEFAULT_PACK])}
    assert names == {head.name for head in SKILLS}


def test_skill_heads_none_returns_all_for_backward_compat() -> None:
    """不传参 = 全集（既有调用点零改动）。"""
    assert skill_heads() == SKILLS


def test_empty_pack_list_returns_no_skills() -> None:
    """**falsy 陷阱第四处**：显式空清单 = 不要技能，不得回退全集。"""
    assert skill_heads([]) == ()


def test_unknown_pack_yields_nothing() -> None:
    assert skill_heads(["nope"]) == ()


def test_pack_filter_selects_only_that_pack() -> None:
    heads = skill_heads([DEFAULT_PACK])
    assert all(head.pack == DEFAULT_PACK for head in heads)


def test_known_packs_reports_default() -> None:
    assert DEFAULT_PACK in known_packs()


def test_skill_body_unchanged_by_pack_refactor() -> None:
    body = skill_body("grilling")
    assert body is not None and body.startswith("# grilling")
    assert skill_body("nope") is None


# ---- assembler 消费面 ----

def _assembler_state(tmp_path: pathlib.Path, **extra) -> dict:
    return {
        "task_brief": "记账 CLI",
        "build_way": "way3",
        "current_scope": "main",
        "todos": [],
        "workspace_root": str(tmp_path),
        **extra,
    }


def test_assembler_injects_skills_from_selected_pack(tmp_path: pathlib.Path) -> None:
    from project_agent.nodes import make_assembler_node

    node = make_assembler_node()
    updates = node(_assembler_state(tmp_path, skill_packs=["default"]), None)
    system = updates["assembled_context"]["system"]
    assert "【技能】" in system
    assert "grilling" in system


def test_assembler_skips_skill_block_when_packs_empty(tmp_path: pathlib.Path) -> None:
    """空白名单 → 不注技能块（**不是**回退全集）。"""
    from project_agent.nodes import make_assembler_node

    node = make_assembler_node()
    updates = node(_assembler_state(tmp_path, skill_packs=[]), None)
    system = updates["assembled_context"]["system"]
    assert "【技能】" not in system


def test_assembler_skips_skill_block_for_unknown_pack(tmp_path: pathlib.Path) -> None:
    from project_agent.nodes import make_assembler_node

    node = make_assembler_node()
    updates = node(_assembler_state(tmp_path, skill_packs=["bogus"]), None)
    assert "【技能】" not in updates["assembled_context"]["system"]


def test_assembler_defaults_to_full_set_when_field_missing(tmp_path: pathlib.Path) -> None:
    """字段未设（None）→ 全集（与 09 票行为一致）。"""
    from project_agent.nodes import make_assembler_node

    node = make_assembler_node()
    updates = node(_assembler_state(tmp_path), None)
    system = updates["assembled_context"]["system"]
    assert "【技能】" in system
    assert "tdd" in system


def test_repl_skills_remove_empties_list(tmp_path: pathlib.Path) -> None:
    """端到端：/skills remove 清空 → 下一轮 assembler 不再注技能块。

    注：`/skills` 改的是 REPL 持有态，桩 app 不回传 state，故直接调内部
    方法验证语义（回放路径由 test_repl_config_commands 覆盖）。
    """
    from project_agent.nodes import make_assembler_node
    from project_agent.repl import ReplHost
    from tests.doubles.scripted_io import ScriptedIO

    class _App:
        def invoke(self, update, config):  # pragma: no cover - 本用例不 invoke
            return {}

    io = ScriptedIO([])
    host = ReplHost(_App(), io, "t")
    host._last_state = {"skill_packs": ["default"]}
    host._skills("/skills remove default")
    assert host._last_state["skill_packs"] == []

    node = make_assembler_node()
    updates = node(_assembler_state(tmp_path, skill_packs=host._last_state["skill_packs"]), None)
    assert "【技能】" not in updates["assembled_context"]["system"]
