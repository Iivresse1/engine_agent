"""终局评审修复：/mode 与 /skills 运行时配置命令（用户故事 3——票拆分漏项补齐）。

- /mode 无参 → 显示当前决策模式与可选项
- /mode {ai_review|manual|中文} → 更新 REPL 持有状态的 decision_mode（写仪表盘字段，
  图内 ShellTool 接线票消费 knobs.from_decision_mode）
- /skills 无参 → 列出已选技能包；/skills add {name} / remove {name} → 增删
  skill_packs 列表（技能头懒加载清单的运行时入口）
"""

from __future__ import annotations

from project_agent.graph import build_graph, new_thread_id
from project_agent.repl import ReplHost
from tests.doubles.scripted_io import ScriptedIO


def _host_with_state(state: dict) -> tuple[ReplHost, ScriptedIO]:
    io = ScriptedIO([])
    host = ReplHost(build_graph(), io, new_thread_id())
    host._last_state = dict(state)
    return host, io


class _StubApp:
    def invoke(self, update, config):
        return {"turn_end_reason": "round", "turn_end_payload": {}}


def _stub_host(state: dict) -> tuple[ReplHost, ScriptedIO]:
    io = ScriptedIO([])
    host = ReplHost(_StubApp(), io, "t-mode")
    host._last_state = dict(state)
    return host, io


# —— /mode：查改决策模式 ——


def test_mode_no_args_shows_current_decision_mode():
    host, io = _stub_host({"build_way": "way3", "decision_mode": "ai_review"})
    host._dispatch("/mode")
    out = "\n".join(io.outputs)
    assert "ai_review" in out
    assert "manual" in out  # 可选项提示


def test_mode_updates_decision_mode():
    host, io = _stub_host({"build_way": "way3", "decision_mode": "ai_review"})
    host._dispatch("/mode manual")
    assert host._last_state["decision_mode"] == "manual"
    assert "manual" in "\n".join(io.outputs)


def test_mode_accepts_chinese_labels():
    host, io = _stub_host({"build_way": "way3", "decision_mode": "ai_review"})
    host._dispatch("/mode 全权人工")
    assert host._last_state["decision_mode"] == "manual"


def test_mode_invalid_value_keeps_and_notifies():
    host, io = _stub_host({"build_way": "way3", "decision_mode": "ai_review"})
    host._dispatch("/mode 乱写")
    assert host._last_state["decision_mode"] == "ai_review"  # 不变
    assert "ai_review" in "\n".join(io.outputs)  # 提示当前值


def test_mode_update_merges_into_next_invoke_update():
    """/mode 改的 decision_mode 进入 REPL 持有态——图内消费接线票就绪。"""
    host, io = _stub_host({"build_way": "way3", "decision_mode": "ai_review"})
    host._dispatch("/mode manual")
    # REPL 持有态已改（下轮 fusion/图输入的受控键源）
    assert host._last_state["decision_mode"] == "manual"


# —— /skills：查改技能包 ——


def test_skills_no_args_lists_selected_packs():
    host, io = _stub_host({"build_way": "way3", "skill_packs": ["default"]})
    host._dispatch("/skills")
    out = "\n".join(io.outputs)
    assert "default" in out


def test_skills_add_appends_pack():
    host, io = _stub_host({"build_way": "way3", "skill_packs": ["default"]})
    host._dispatch("/skills add extra")
    assert host._last_state["skill_packs"] == ["default", "extra"]


def test_skills_remove_drops_pack():
    host, io = _stub_host({"build_way": "way3", "skill_packs": ["default", "extra"]})
    host._dispatch("/skills remove extra")
    assert host._last_state["skill_packs"] == ["default"]


def test_skills_add_duplicate_noop():
    host, io = _stub_host({"build_way": "way3", "skill_packs": ["default"]})
    host._dispatch("/skills add default")
    assert host._last_state["skill_packs"] == ["default"]


def test_skills_invalid_subcommand_notifies():
    host, io = _stub_host({"build_way": "way3", "skill_packs": ["default"]})
    host._dispatch("/skills 乱写")
    assert host._last_state["skill_packs"] == ["default"]
    assert "用法" in "\n".join(io.outputs)


def test_help_lists_mode_and_skills():
    host, io = _stub_host({})
    host._dispatch("/help")
    out = "\n".join(io.outputs)
    assert "/mode" in out
    assert "/skills" in out
