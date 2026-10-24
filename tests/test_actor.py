"""actor 节点工厂（05 票终裁 7）：模型调用、todos 勾选、隔离红线。

切片 3：assembler→actor→END 临时直连（verifier 切片 4 接入）；
model=None → 05 骨架 round_end，不调模型不产 AIMessage。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_actor_node
from project_agent.routing import CONTEXT_ASSEMBLER, entry_route
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]


def _cfg(thread: str = "t-actor") -> dict:
    return {"configurable": {"thread_id": thread}}


def _assembled(todos: list) -> dict:
    return {
        "system": "你是构建 agent。当前方式 way1，指引 off，待办 2 项",
        "todo_board": [f"pending: {t['content']}" for t in todos],
        "scope": "main",
    }


def test_entry_route_row4_uncleared_todos_to_context_assembler():
    assert entry_route({"task_brief": "x", "build_way": "way1", "todos": TWO_PENDING}) == CONTEXT_ASSEMBLER
    assert entry_route(
        {
            "task_brief": "x",
            "build_way": "way1",
            "todos": [
                {"content": "a", "status": "completed"},
                {"content": "b", "status": "in_progress"},
            ],
        }
    ) == CONTEXT_ASSEMBLER


def test_entry_route_cleared_todos_still_planner_until_verifier_slice():
    """切片 3 阶段：todos 清暂回落 planner（行 5/7 切片 4 落位）。"""
    assert (
        entry_route(
            {
                "task_brief": "x",
                "build_way": "way1",
                "todos": [{"content": "a", "status": "completed"}],
            }
        )
        == "planner"
    )


def test_actor_model_none_writes_skeleton_round_end():
    node = make_actor_node(None)
    state = {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING)}
    updates = node(state, _cfg())
    assert updates["turn_end_reason"] == "round"
    assert "主环待真模型接入" in updates["turn_end_payload"]["round_output"]
    assert "actor_messages" not in updates  # 不产 AIMessage
    assert "todos" not in updates  # 无产出不勾选


def test_actor_calls_model_with_system_plus_actor_history():
    model = ScriptedModel(["回复甲"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [HumanMessage(content="你好"), AIMessage(content="旧回复")],
    }
    updates = node(state, _cfg("tid-9"))
    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["role"] == "actor"
    assert call["thread_id"] == "tid-9"
    assert call["messages"] == [
        {"role": "system", "content": "你是构建 agent。当前方式 way1，指引 off，待办 2 项"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "旧回复"},
    ]
    assert updates["actor_messages"] == [AIMessage(content="回复甲")]
    assert updates["turn_end_payload"]["round_output"] == "回复甲"


def test_actor_checks_todos_by_exact_completion_marker():
    """响应文本含 f"完成：{content}" 子串 → 置 completed；匹配不到跳过。"""
    model = ScriptedModel(["好的，完成：梳理需求边界，继续下一步。"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [HumanMessage(content="推进")],
    }
    updates = node(state, _cfg())
    assert [item["status"] for item in updates["todos"]] == ["completed", "pending"]
    # round_end 的 todo_board 用勾选后的板
    board = updates["turn_end_payload"]["todo_board"]
    assert board == ["completed: 梳理需求边界", "pending: 推进对话任务"]


def test_actor_todo_check_requires_exact_content():
    """精确匹配：响应只含近似文本（缺完整 content）不勾选。"""
    model = ScriptedModel(["完成：梳理需求"])  # 不是完整 content
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [],
    }
    updates = node(state, _cfg())
    assert [item["status"] for item in updates["todos"]] == ["pending", "pending"]


def test_actor_skips_completed_and_checks_in_progress():
    """completed 项不再处理；in_progress 项可勾。"""
    todos = [
        {"content": "梳理需求边界", "status": "completed"},
        {"content": "推进对话任务", "status": "in_progress"},
    ]
    model = ScriptedModel(["完成：推进对话任务"])
    node = make_actor_node(model)
    updates = node(
        {"todos": todos, "assembled_context": _assembled(todos), "actor_messages": []},
        _cfg(),
    )
    assert [item["status"] for item in updates["todos"]] == ["completed", "completed"]


def test_actor_isolation_redline_no_demo_history_in_model_calls():
    """验收 7：model.calls 的 messages 只含 system+actor 历史——demo 私有历史绝不出现。"""
    marker = "DEMO_PRIVATE_MARKER_XYZ"
    model = ScriptedModel(["回复"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [HumanMessage(content="主线输入")],
        "demo_messages": [HumanMessage(content=f"demo 私密 {marker}"), AIMessage(content=marker)],
    }
    node(state, _cfg())
    for call in model.calls:
        for message in call["messages"]:
            assert marker not in str(message.values())


def test_graph_assembler_actor_flow_with_model():
    """图级：todos 未清 → context_assembler → actor → verifier（未清 END）。"""
    model = ScriptedModel(["完成：梳理需求边界。", "task_complete: false"])
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=model)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-actor-1"),
    )
    assert r["turn_end_reason"] == "round"
    assert r["turn_end_payload"]["round_output"] == "完成：梳理需求边界。"
    assert [item["status"] for item in r["todos"]] == ["completed", "pending"]
    assert r["assembled_context"]["scope"] == "main"
    assert len(model.calls) == 2  # actor + verifier
    assert model.calls[0]["role"] == "actor"
    assert model.calls[1]["role"] == "verifier"


def test_graph_model_none_actor_skeleton_inert():
    """model=None：assembler→actor→END 不挂死，05 骨架 round_end。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver)
    r = app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "guidance_mode": "off",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="开始")],
        },
        _cfg("g-actor-2"),
    )
    assert r["turn_end_reason"] == "round"
    assert "主环待真模型接入" in r["turn_end_payload"]["round_output"]
    assert [item["status"] for item in r["todos"]] == ["pending", "pending"]


def test_graph_isolation_redline_seeded_demo_messages():
    """图级验收 7：seed demo_messages 带独特标记 → 绝不出现在任何 model 调用。"""
    marker = "DEMO_PRIVATE_MARKER_ABC"
    model = ScriptedModel(["回复乙", "task_complete: false"])
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=model)
    app.invoke(
        {
            "task_brief": "想法",
            "build_way": "way1",
            "todos": TWO_PENDING,
            "actor_messages": [HumanMessage(content="主线")],
            "demo_messages": [HumanMessage(content=f"demo 侧 {marker}")],
        },
        _cfg("g-actor-3"),
    )
    assert model.calls
    for call in model.calls:
        for message in call["messages"]:
            assert marker not in str(message.values())


# —— 06：actor 扩展（round_count/落盘/记录：指令解析/notes_version 自增）——

R1_TEXT = "推进中。记录：登录页要用浅色主题"
R2_TEXT = "继续。记录：接口超时需设 30 秒。记录：错误码统一 5 位"


def test_actor_shared_docs_none_behavior_identical_to_05():
    """shared_docs=None：行为与 05 完全一致（无 round_count 写仪表盘、不落盘）。"""
    model = ScriptedModel(["回复丙"])
    node = make_actor_node(model)  # shared_docs 缺省 None
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [],
    }
    updates = node(state, _cfg())
    assert updates["actor_messages"] == [AIMessage(content="回复丙")]
    assert "round_count" not in updates  # 05 行为：无此字段
    assert "notes_version" not in updates


def test_actor_round_count_first_working_round_is_one(tmp_path):
    """首个工作轮 round_count=1（【R1】）。"""
    model = ScriptedModel([R1_TEXT])
    node = make_actor_node(model, shared_docs=SharedDocs(tmp_path))
    updates = node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    assert updates["round_count"] == 1


def test_actor_round_count_increments_from_state(tmp_path):
    """round_count = (state round_count or 0)+1；state 无键→1。"""
    model = ScriptedModel(["回复"])
    node = make_actor_node(model, shared_docs=SharedDocs(tmp_path))
    updates = node(
        {
            "todos": TWO_PENDING,
            "assembled_context": _assembled(TWO_PENDING),
            "actor_messages": [],
            "round_count": 4,
        },
        _cfg(),
    )
    assert updates["round_count"] == 5


def test_actor_appends_full_model_text_with_round_marker(tmp_path):
    """每轮生成物带【R#】：BUILD_LOG 落盘模型全文，切片只返回该轮。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel([R1_TEXT])
    node = make_actor_node(model, shared_docs=docs)
    node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    assert docs.read_rounds() == [(1, f"【R1】{R1_TEXT}")]


def test_actor_round_count_persists_across_writes(tmp_path):
    """跨轮编号连续：R1 后 R2（BUILD_LOG 连续编号溯源）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel([R1_TEXT, R2_TEXT])
    node = make_actor_node(model, shared_docs=docs)
    node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    node(
        {
            "todos": TWO_PENDING,
            "assembled_context": _assembled(TWO_PENDING),
            "actor_messages": [],
            "round_count": 1,
        },
        _cfg(),
    )
    assert docs.read_rounds() == [(1, f"【R1】{R1_TEXT}"), (2, f"【R2】{R2_TEXT}")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 中段：取分隔符后到下一分隔符/文末
        ("推进中。记录：登录页要用浅色主题", [(1, "登录页要用浅色主题")]),
        # 文首即指令
        ("记录：登录页要用浅色主题", [(1, "登录页要用浅色主题")]),
        # 多条（票面「可多条」：split 全部出现处）且跨行
        ("开头记录：甲。后续\n记录：乙", [(1, "甲。后续"), (1, "乙")]),
        # 段尾空白 strip（前导空格也剥）
        ("记录：  带前导空格  ", [(1, "带前导空格")]),
    ],
    ids=["mid-text", "prefix", "two-across-lines", "surrounding-spaces"],
)
def test_actor_note_parsing_table_driven(tmp_path, text, expected):
    """「记录：{note}」子串→逐条 notepad_add；非空段、段尾空白 strip。"""
    docs = SharedDocs(tmp_path)
    node = make_actor_node(ScriptedModel([text]), shared_docs=docs)
    node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    assert docs.notepad_entries() == expected


def test_actor_note_version_increments_by_written_entries(tmp_path):
    """notes_version = 旧值+写入条数（单调自增）。"""
    docs = SharedDocs(tmp_path)
    node = make_actor_node(ScriptedModel([R2_TEXT]), shared_docs=docs)  # 2 条
    updates = node(
        {
            "todos": TWO_PENDING,
            "assembled_context": _assembled(TWO_PENDING),
            "actor_messages": [],
            "notes_version": 3,
        },
        _cfg(),
    )
    assert updates["notes_version"] == 5


def test_actor_note_version_from_zero_when_no_notes(tmp_path):
    """响应无「记录：」→零条写入、notes_version 不写键（旧值=0 + 0）。"""
    docs = SharedDocs(tmp_path)
    node = make_actor_node(ScriptedModel(["无记录指令"]), shared_docs=docs)
    updates = node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    assert docs.notepad_entries() == []
    assert updates["notes_version"] == 0  # 旧值 0 + 0 条
    assert docs.notepad_entries() == []


def test_actor_round_summary_and_turn_end_unchanged(tmp_path):
    """round_summary/turn_end 照旧（round_end 板用勾选后 todos，05 既有）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["完成：梳理需求边界。记录：甲注记"])
    node = make_actor_node(model, shared_docs=docs)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled(TWO_PENDING),
        "actor_messages": [HumanMessage(content="推进")],
    }
    updates = node(state, _cfg())
    assert updates["round_summary"] == "完成：梳理需求边界。记录：甲注记"
    assert updates["turn_end_reason"] == "round"
    assert updates["turn_end_payload"]["round_output"] == "完成：梳理需求边界。记录：甲注记"
    board = updates["turn_end_payload"]["todo_board"]
    assert board == ["completed: 梳理需求边界", "pending: 推进对话任务"]
    assert docs.notepad_entries() == [(1, "甲注记")]


def test_actor_model_none_with_shared_docs_still_skeleton(tmp_path):
    """model=None 优先：即便传入 shared_docs 也走 05 骨架（不落盘）。"""
    docs = SharedDocs(tmp_path)
    node = make_actor_node(None, shared_docs=docs)
    state = {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING)}
    updates = node(state, _cfg())
    assert updates["turn_end_reason"] == "round"
    assert "主环待真模型接入" in updates["turn_end_payload"]["round_output"]
    assert docs.read_rounds() == []
    assert docs.notepad_entries() == []
    assert "round_count" not in updates
    assert "notes_version" not in updates


def test_actor_note_parsing_skips_empty_segments(tmp_path):
    """空段跳过：分隔符相邻/尾部空段不产条目。"""
    docs = SharedDocs(tmp_path)
    node = make_actor_node(ScriptedModel(["记录：记录："]), shared_docs=docs)
    node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    assert docs.notepad_entries() == []


# —— 09：actor 送达扩展（工具子集尾行 + 技能懒加载触发桩 + 推荐理由截断桩）——


def _assembled_with_tools(todos: list, tools: list[str]) -> dict:
    ctx = _assembled(todos)
    ctx["tools_subset"] = tools
    return ctx


def test_actor_appends_tools_subset_line_to_system():
    """工具子集送达：system 尾行 "【可用工具】a、b、c"（子集=assembler 装的交集）。"""
    model = ScriptedModel(["回复"])
    node = make_actor_node(model)
    state = {
        "todos": TWO_PENDING,
        "assembled_context": _assembled_with_tools(
            TWO_PENDING, ["FileEdit", "FileRead", "Glob"]
        ),
        "actor_messages": [],
    }
    node(state, _cfg())
    system = model.calls[0]["messages"][0]["content"]
    assert system.endswith("【可用工具】FileEdit、FileRead、Glob")
    assert system.startswith("你是构建 agent")


def test_actor_empty_tools_subset_leaves_system_untouched():
    """子集空/缺键 → system 照旧（零尾行）。"""
    model = ScriptedModel(["回复"])
    node = make_actor_node(model)
    node(
        {
            "todos": TWO_PENDING,
            "assembled_context": _assembled(TWO_PENDING),  # 无 tools_subset 键
            "actor_messages": [],
        },
        _cfg(),
    )
    assert model.calls[0]["messages"][0]["content"] == "你是构建 agent。当前方式 way1，指引 off，待办 2 项"


def test_actor_skill_trigger_round_end_hint(tmp_path):
    """技能懒加载触发桩：响应含 "技能：tdd" → round_end 提示 "技能 tdd 已全文载入"
    （skill_body 读出即触发——不进模型调用）。AIMessage/落盘/round_summary 保持模型原文。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["本轮采用 技能：tdd 推进"])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    out = updates["turn_end_payload"]["round_output"]
    assert out.startswith("本轮采用 技能：tdd 推进")
    assert "技能 tdd 已全文载入" in out
    # 模型调用只有一次（触发不进模型调用）
    assert len(model.calls) == 1
    # AIMessage 与落盘保持模型原文
    assert updates["actor_messages"] == [AIMessage(content="本轮采用 技能：tdd 推进")]
    assert docs.read_rounds() == [(1, "【R1】本轮采用 技能：tdd 推进")]
    assert updates["round_summary"] == "本轮采用 技能：tdd 推进"


def test_actor_skill_trigger_ignored_without_shared_docs():
    """无 shared_docs → 零提示（round_output=模型全文）。"""
    model = ScriptedModel(["用 技能：tdd 做"])
    node = make_actor_node(model)  # shared_docs 缺省 None
    updates = node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    assert updates["turn_end_payload"]["round_output"] == "用 技能：tdd 做"


def test_actor_skill_trigger_unknown_skill_ignored(tmp_path):
    """无 name 命中 → 忽略（零提示）。"""
    docs = SharedDocs(tmp_path)
    model = ScriptedModel(["聊聊 技能：nosuch 的事"])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    assert updates["turn_end_payload"]["round_output"] == "聊聊 技能：nosuch 的事"


def test_actor_recommendation_reason_truncated_to_20(tmp_path):
    """推荐理由截断桩：响应含 "推荐技能：{name}（{reason}）" → reason 过
    recommendation_reason（30 字→20）；不误触发普通技能载入提示。"""
    docs = SharedDocs(tmp_path)
    reason_30 = "一二三四五六七八九十" * 3
    model = ScriptedModel([f"我的建议是 推荐技能：grilling（{reason_30}） 供参考"])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(
        {"todos": TWO_PENDING, "assembled_context": _assembled(TWO_PENDING), "actor_messages": []},
        _cfg(),
    )
    out = updates["turn_end_payload"]["round_output"]
    assert f"推荐技能：grilling（{reason_30[:20]}）" in out
    assert reason_30 not in out  # 全文 30 字不再出现
    # 推荐模式不误触发 "技能 grilling 已全文载入"
    assert "已全文载入" not in out

