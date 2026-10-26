"""17 票：decision_mode / skill_packs 的图内消费者（清两条欠账）。"""

from __future__ import annotations

import pathlib

from project_agent.model_client import ModelResult, ToolAwareResult, ToolCall
from project_agent.nodes import _actor_tool_runner, make_actor_node


class _ShellModel:
    """请求执行一条 shell 命令，再给终稿。"""

    def __init__(self, command: str = "echo hi") -> None:
        self.command = command
        self._script = [
            ToolAwareResult(
                text="跑个命令",
                tool_calls=(ToolCall(id="c1", name="Shell", arguments={"command": command}),),
            ),
            ToolAwareResult(text="跑完了"),
        ]

    def complete(self, messages, *, role, thread_id):  # pragma: no cover
        return ModelResult(text="unused")

    def complete_with_tools(self, messages, tools, *, role, thread_id):
        return self._script.pop(0)


def _state(tmp_path: pathlib.Path, **extra) -> dict:
    return {
        "task_brief": "记个账",
        "build_way": "way1",
        "workspace_root": str(tmp_path),
        "actor_messages": [],
        **extra,
    }


def test_runner_exposes_knobs_derived_from_decision_mode(tmp_path: pathlib.Path) -> None:
    """decision_mode → 两旋钮初值（这是该字段的第一个图内消费者）。"""
    runner, knobs = _actor_tool_runner(_state(tmp_path, decision_mode="ai_review"))
    assert knobs.ask_level() == "ai_review"
    runner2, knobs2 = _actor_tool_runner(_state(tmp_path, decision_mode="manual"))
    assert knobs2.ask_level() == "human"


def test_runner_falls_back_to_ai_review_for_unknown_mode(tmp_path: pathlib.Path) -> None:
    """未识别决策模式 → fail-closed 到审核档（不抛、不静默放开）。"""
    _runner, knobs = _actor_tool_runner(_state(tmp_path, decision_mode="banana"))
    assert knobs.ask_level() == "ai_review"


def test_manual_mode_denies_shell_in_graph(tmp_path: pathlib.Path) -> None:
    """全权人工档：图内无交互通道 → shell 一律拒（fail-closed），文件工具不受影响。"""
    model = _ShellModel("echo hi")

    class _TwoRoundModel(_ShellModel):
        """第一轮请求 shell，第二轮终稿（确保拿到工具结果）。"""

        def __init__(self) -> None:
            super().__init__("echo hi")

    node = make_actor_node(_TwoRoundModel())
    updates = node(_state(tmp_path, decision_mode="manual"), None)
    content = updates["actor_messages"][0].content
    assert "跑完了" in content
    assert "成功 0" in content, f"manual 档应拒 shell，实际：{content}"


def test_ai_review_mode_allows_safe_shell(tmp_path: pathlib.Path) -> None:
    """AI 审核档：静态检查放行的安全命令可执行（echo 不触静态 deny）。"""
    model = _ShellModel("echo hi")
    node = make_actor_node(model)
    updates = node(_state(tmp_path, decision_mode="ai_review"), None)
    content = updates["actor_messages"][0].content
    assert "工具调用 1 次（成功 1）" in content


def test_file_tools_work_regardless_of_decision_mode(tmp_path: pathlib.Path) -> None:
    """审核档只影响 shell；文件工具有路径约束，两个档位都应可用。"""

    class _WriteModel:
        def __init__(self) -> None:
            self._script = [
                ToolAwareResult(
                    text="写",
                    tool_calls=(
                        ToolCall(id="c", name="FileWrite", arguments={"path": "a.md", "content": "x"}),
                    ),
                ),
                ToolAwareResult(text="写好了"),
            ]

        def complete(self, m, *, role, thread_id):  # pragma: no cover
            return ModelResult(text="unused")

        def complete_with_tools(self, m, t, *, role, thread_id):
            return self._script.pop(0)

    for mode in ("ai_review", "manual"):
        target = tmp_path / mode
        target.mkdir()
        node = make_actor_node(_WriteModel())
        updates = node(_state(target, decision_mode=mode), None)
        assert (target / "a.md").is_file(), f"{mode} 档下文件工具应可用"
        assert "工具调用 1 次（成功 1）" in updates["actor_messages"][0].content


def test_dangerous_shell_still_denied_by_static_checker_in_graph(tmp_path: pathlib.Path) -> None:
    """即便 AI 审核档，静态正则仍拦危险命令（两档都拦）。"""
    model = _ShellModel("rm -rf /")
    node = make_actor_node(model)
    updates = node(_state(tmp_path, decision_mode="ai_review"), None)
    content = updates["actor_messages"][0].content
    assert "成功 0" in content, f"危险命令应被静态检查器拦下，实际：{content}"
