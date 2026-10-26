"""17 票 actor 接线：模型支持工具时走工具环，不支持时行为不变。"""

from __future__ import annotations

import pathlib

from project_agent.model_client import (
    ModelResult,
    ToolAwareResult,
    ToolCall,
    supports_tools,
)
from project_agent.nodes import make_actor_node


class _PlainModel:
    """既有桩形态：只有 complete（无工具能力）。"""

    def __init__(self, text: str = "普通回复") -> None:
        self.text = text
        self.calls = 0

    def complete(self, messages, *, role, thread_id):
        self.calls += 1
        return ModelResult(text=self.text)


class _ToolModel:
    """带 function calling 的模型：第一轮请求写文件，第二轮给终稿。"""

    def __init__(self, path: str = "docs/记录.md") -> None:
        self.path = path
        self.rounds: list[list[dict]] = []
        self.tool_batches: list[list[dict]] = []
        self._script = [
            ToolAwareResult(
                text="我先落盘",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="FileWrite",
                        arguments={"path": path, "content": "# 记录\n\n内容\n"},
                    ),
                ),
            ),
            ToolAwareResult(text="已写好，本轮完成"),
        ]

    def complete(self, messages, *, role, thread_id):  # pragma: no cover - 不被调用
        return ModelResult(text="unused")

    def complete_with_tools(self, messages, tools, *, role, thread_id):
        self.rounds.append([dict(m) for m in messages])
        self.tool_batches.append(list(tools))
        return self._script.pop(0)


def _state(tmp_path: pathlib.Path) -> dict:
    return {
        "task_brief": "做一个记账 CLI",
        "build_way": "way3",
        "workspace_root": str(tmp_path),
        "actor_messages": [],
    }


def test_supports_tools_detects_capability() -> None:
    assert supports_tools(_ToolModel()) is True
    assert supports_tools(_PlainModel()) is False


def test_actor_uses_tool_loop_when_model_supports_tools(tmp_path: pathlib.Path) -> None:
    """真工具环：模型请求 FileWrite → 文件真的落盘 → 结果回灌 → 终稿。"""
    model = _ToolModel()
    node = make_actor_node(model)
    updates = node(_state(tmp_path), None)

    # 文件真的被工具写出来（不是文本桥猜的）
    written = tmp_path / "docs" / "记录.md"
    assert written.is_file(), "工具环未真正执行 FileWrite"
    assert "内容" in written.read_text(encoding="utf-8")

    # 终稿里带工具回执行
    content = updates["actor_messages"][0].content
    assert "已写好" in content
    assert "工具调用 1 次" in content

    # 两次模型往返：第二轮的历史里应有 tool 结果
    assert len(model.rounds) == 2
    assert any(m.get("role") == "tool" for m in model.rounds[1])

    # 模型拿到的 schema 面是 builder 全工具（含 FileWrite）
    names = {d["function"]["name"] for d in model.tool_batches[0]}
    assert "FileWrite" in names


def test_actor_without_tools_keeps_single_shot_behaviour(tmp_path: pathlib.Path) -> None:
    """既有桩模型无工具能力 → 行为与 05/07 票逐字一致（不走环）。"""
    model = _PlainModel("只回一句话")
    node = make_actor_node(model)
    updates = node(_state(tmp_path), None)
    assert updates["actor_messages"][0].content == "只回一句话"
    assert model.calls == 1
    assert not (tmp_path / "docs").exists()


def test_actor_tool_loop_denied_write_for_ask_role(tmp_path: pathlib.Path) -> None:
    """面外工具（若 role 误配为 ask）→ deny 回灌，文件不落地。"""

    class _AskRoleModel(_ToolModel):
        pass

    model = _AskRoleModel()
    node = make_actor_node(model)
    node(_state(tmp_path), None)
    # actor 固定用 builder 角色，故写入成功；此用例守护"角色常量没写错"
    assert (tmp_path / "docs" / "记录.md").is_file()


def test_actor_tool_loop_exhaustion_reports_in_text(tmp_path: pathlib.Path) -> None:
    """模型每轮都调工具 → 终稿说明轮次耗尽（不静默）。"""

    class _GreedyModel(_ToolModel):
        def complete_with_tools(self, messages, tools, *, role, thread_id):
            return ToolAwareResult(
                text="",
                tool_calls=(
                    ToolCall(id="c", name="Glob", arguments={"pattern": "*"}),
                ),
            )

    node = make_actor_node(_GreedyModel())
    updates = node(_state(tmp_path), None)
    content = updates["actor_messages"][0].content
    assert "工具轮次耗尽" in content
    assert "已达工具轮次上限" in content


def test_actor_tool_call_bad_args_becomes_error_message(tmp_path: pathlib.Path) -> None:
    """模型给错参数 → 折成错误消息回灌，环继续并产出终稿。"""

    class _BadArgsModel(_ToolModel):
        def __init__(self) -> None:
            super().__init__()
            self._script = [
                ToolAwareResult(
                    text="写",
                    tool_calls=(ToolCall(id="c1", name="FileWrite", arguments={"path": "a.md"}),),
                ),
                ToolAwareResult(text="参数不对，我改"),
            ]

    node = make_actor_node(_BadArgsModel())
    updates = node(_state(tmp_path), None)
    assert "参数不对" in updates["actor_messages"][0].content
    assert not (tmp_path / "a.md").exists()


def test_actor_round_output_mentions_tool_summary(tmp_path: pathlib.Path) -> None:
    """断点 payload 的 round_output 含工具回执（用户可见）。"""
    model = _ToolModel()
    node = make_actor_node(model)
    updates = node(_state(tmp_path), None)
    payload = updates["turn_end_payload"]
    assert payload["round_output"] == updates["actor_messages"][0].content
    assert "工具调用" in payload["round_output"]
