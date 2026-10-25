"""协议消息层（UX-2）的形状契约——spec v2.1『协议消息层』节的代码化断言。

表即契约：本文件逐行断言 `DOWN_MESSAGES` / `UP_MESSAGES` 与 spec 消息表一致，
并覆盖信封校验（缺字段/多字段/错类型/未知 type）、终端降级渲染、红线哨兵。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from project_agent.messages import (
    DOWN_MESSAGES,
    UP_MESSAGES,
    MessageError,
    decode,
    default_rendering,
    encode,
    round_end_message,
)
from tests.doubles.scripted_io import ScriptedIO

# spec v2.1『协议消息层』消息表逐行镜像——改代码必须同步改 spec，反之亦然
SPEC_DOWN_ROWS = [
    ("ready", ("banner", "opening_prompt")),
    ("prompt", ("awaiting",)),
    ("round_end", ("reason", "payload", "lines")),
    ("notice", ("text",)),
    ("teach_page", ("path", "round")),
    ("farewell", ("text",)),
]
SPEC_UP_ROWS = [
    ("input", ("text",)),
    ("quit", ()),
]


def test_down_messages_match_spec_table():
    assert list(DOWN_MESSAGES) == [kind for kind, _ in SPEC_DOWN_ROWS]
    for kind, fields in SPEC_DOWN_ROWS:
        assert DOWN_MESSAGES[kind].fields == fields


def test_up_messages_match_spec_table():
    assert list(UP_MESSAGES) == [kind for kind, _ in SPEC_UP_ROWS]
    for kind, fields in SPEC_UP_ROWS:
        assert UP_MESSAGES[kind].fields == fields


def test_encode_round_end_envelope_is_single_layer():
    message = encode(
        "round_end",
        reason="question",
        payload={"question_text": "要不要讲解？"},
        lines=["要不要讲解？"],
    )
    assert set(message) == {"type", "reason", "payload", "lines"}
    assert message["type"] == "round_end"


def test_encode_rejects_missing_field():
    with pytest.raises(MessageError, match="缺少必填字段"):
        encode("notice")  # 少 text


def test_encode_rejects_unknown_field():
    with pytest.raises(MessageError, match="协议外字段"):
        encode("notice", text="hi", extra="oops")


def test_encode_rejects_unknown_kind():
    with pytest.raises(MessageError, match="未知下行消息类型"):
        encode("nope")


def test_encode_rejects_wrong_type():
    with pytest.raises(MessageError, match="应为 str"):
        encode("notice", text=1)


def test_round_end_payload_must_be_dict():
    with pytest.raises(MessageError, match="应为 dict"):
        encode("round_end", reason="round", payload=[], lines=[])


def test_round_end_lines_must_be_list_of_str():
    with pytest.raises(MessageError, match="应为 list\\[str\\]"):
        encode("round_end", reason="round", payload={}, lines=[1])


def test_teach_page_round_must_be_int_and_reject_bool():
    assert encode("teach_page", path="teach-me/R1/index.html", round=1)["round"] == 1
    with pytest.raises(MessageError, match="应为 int"):
        encode("teach_page", path="x", round=True)


def test_decode_input_ok():
    assert decode({"type": "input", "text": "今天要做什么呢？"}) == {
        "type": "input",
        "text": "今天要做什么呢？",
    }


def test_decode_quit_needs_no_fields():
    assert decode({"type": "quit"}) == {"type": "quit"}


def test_decode_rejects_unknown_type():
    with pytest.raises(MessageError, match="未知上行消息类型"):
        decode({"type": "resume", "value": 1})


def test_decode_rejects_missing_field():
    with pytest.raises(MessageError, match="缺少必填字段"):
        decode({"type": "input"})


def test_decode_rejects_unknown_field():
    with pytest.raises(MessageError, match="协议外字段"):
        decode({"type": "quit", "text": "多余"})


def test_decode_rejects_non_mapping():
    with pytest.raises(MessageError, match="必须是 mapping"):
        decode(["not", "a", "mapping"])


def test_default_rendering_ready_is_two_part_opening():
    lines = default_rendering(
        "ready", {"banner": "Project Agent。输入 /help 查看命令。", "opening_prompt": "今天要做什么呢？"}
    )
    assert lines == ["Project Agent。输入 /help 查看命令。", "", "今天要做什么呢？"]


def test_default_rendering_prompt_empty_when_no_awaiting():
    assert default_rendering("prompt", {"awaiting": ""}) == []
    assert default_rendering("prompt", {"awaiting": "actor"}) == ["等待输入 · actor"]


def test_default_rendering_round_end_prefixes_reason():
    lines = default_rendering("round_end", {"reason": "question", "payload": {}, "lines": ["问题正文"]})
    assert lines == ["断点 · question", "问题正文"]


def test_default_rendering_notice_and_farewell():
    assert default_rendering("notice", {"text": "已压缩 5 轮"}) == ["已压缩 5 轮"]
    assert default_rendering("farewell", {"text": "再见"}) == ["再见"]


def test_default_rendering_teach_page_receipt():
    assert default_rendering("teach_page", {"path": "teach-me/R1/index.html", "round": 1}) == [
        "教学页已生成：teach-me/R1/index.html"
    ]


def test_default_rendering_rejects_unknown_kind():
    with pytest.raises(MessageError, match="未知下行消息类型"):
        default_rendering("nope", {})


def test_round_end_message_helper_matches_encode():
    message = round_end_message("round", {"round_output": "产出"}, ["产出"])
    assert message == encode("round_end", reason="round", payload={"round_output": "产出"}, lines=["产出"])


def test_encode_output_is_json_serializable():
    import json

    message = round_end_message("finished", {"delivery_paths": {"clean": "clean/"}}, ["clean/"])
    assert json.loads(json.dumps(message)) == message


def test_render_breakpoint_lines_dispatches_by_reason():
    """决议类断点必须走三层渲染（冒烟发现：choice 曾整 dict 平铺）。"""
    from project_agent.rendering import render_breakpoint_lines

    build_way = {
        "explanation": "决定 agent 用多重的流程陪你把这个项目做出来",
        "options": ["对话 —— 像聊天一样推进，不产出文档", "完整文档 —— 完整规格/ADR"],
        "recommendation": "简化文档 —— 核心 README/TODO",
        "recommendation_reason": "个人作品有沉淀不臃肿",
    }
    lines = render_breakpoint_lines("choice:build_way", build_way, ansi=False)
    joined = "\n".join(lines)
    assert "决定 agent 用多重的流程" in joined
    assert "1. 对话 —— 像聊天一样推进" in joined
    assert "推荐：简化文档" in joined
    assert "个人作品有沉淀不臃肿" in joined  # ≤20 字理由独立成行
    # round 类仍逐字段平铺（不是三层渲染）
    flat = render_breakpoint_lines("round", {"round_output": "产出"}, ansi=False)
    assert flat == ["  round_output: 产出"]


def test_messages_module_has_no_graph_dependency():
    """红线哨兵（ADR-0005）：协议层不得反向依赖图/节点/模型——否则即倒退。"""
    source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "project_agent" / "messages.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "project_agent.nodes",
        "project_agent.graph",
        "project_agent.runtime",
        "project_agent.model_client",
        "project_agent.repl",
        "langgraph",
        "langchain_core",
    }
    assert imported & forbidden == set(), f"协议层不得依赖图/模型: {sorted(imported & forbidden)}"


def test_repl_opening_sequence_uses_ready_message(workspace):
    """UX-2：REPL 开场序列由 ready 消息折叠而来（横幅、空行、开场提示三行）。"""
    from project_agent.repl import ReplHost

    class StubApp:
        def invoke(self, update, config):  # pragma: no cover - 本用例不 invoke
            return {}

    io = ScriptedIO(["/exit"])
    ReplHost(StubApp(), io, "t-1").run()
    assert io.outputs[:4] == [
        "Project Agent。输入 /help 查看命令。",
        "",
        "今天要做什么呢？",
        "再见",
    ]


def test_repl_round_end_matches_message_layer(workspace):
    """UX-2：REPL 断点交付 = 协议消息层的终端降级渲染（同一份折叠逻辑）。"""
    from project_agent.repl import ReplHost

    payload = {"delivery_paths": {"clean": "clean/"}}

    class StubApp:
        def invoke(self, update, config):
            return {"turn_end_reason": "finished", "turn_end_payload": payload}

    io = ScriptedIO(["hello", "/exit"])
    ReplHost(StubApp(), io, "t-2").run()
    expected = default_rendering("round_end", round_end_message("finished", payload, []))
    assert expected[0] == "断点 · finished"
    assert expected[0] in io.outputs

