"""10 票切片 3：图内新手指引后置工序（版本门/材料包/对齐/隔离红线）。"""

from __future__ import annotations

from project_agent.nodes import make_actor_node
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

ACTOR_MARKER = "ACTOR_PRIVATE_MARKER_G10"
DEMO_MARKER = "DEMO_PRIVATE_MARKER_G10"
GUIDANCE_TEXT = "指引：因为用了 React，下一步推进 todo 板。"


def _cfg(thread: str = "t-guidance") -> dict:
    return {"configurable": {"thread_id": thread}}


def _state(mode: str | None = "auto", notes_version: int = 2, read: int = 0) -> dict:
    state = {
        "build_way": "way1",
        "todos": [{"content": "梳理需求边界", "status": "pending"}],
        "assembled_context": {"system": "你是构建 agent。", "todo_board": [], "scope": "main"},
        "actor_messages": [],
        "notes_version": notes_version,
        "guidance_read_version": read,
        "round_count": 2,
    }
    if mode is not None:
        state["guidance_mode"] = mode
    return state


def _docs(tmp_path) -> SharedDocs:
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "第一轮文档")
    docs.append_round_entry(2, "第二轮文档：React 技术栈")
    docs.notepad_add(1, "浅色主题")
    docs.notepad_add(2, "错误码五位")
    return docs


def test_actor_auto_guidance_injects_and_aligns_version(tmp_path):
    """auto + 版本差>0：材料包单发 ask_agent，指引进 round_output 尾部，版本对齐。"""
    docs = _docs(tmp_path)
    model = ScriptedModel(["actor 产出文本", GUIDANCE_TEXT])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(_state("auto"), _cfg())

    assert len(model.calls) == 2
    actor_call, ask_call = model.calls
    assert actor_call["role"] == "actor"
    assert ask_call["role"] == "ask_agent"
    assert ask_call["thread_id"] == "t-guidance"
    assert len(ask_call["messages"]) == 1  # 材料包单发，无历史累积
    material = ask_call["messages"][0]["content"]
    assert "为什么这么做" in material
    assert "下一步：推进 todo 板" in material
    assert "【R1】- 浅色主题" in material  # 最新 NOTE 条目
    assert "【R3】actor 产出文本" in material  # 最新轮文档切片

    # 指引只进 round_output 尾部；主线私有 key 零污染
    assert updates["turn_end_payload"]["round_output"].endswith(GUIDANCE_TEXT)
    assert updates["actor_messages"][0].content == "actor 产出文本"
    assert updates["round_summary"] == "actor 产出文本"
    assert updates["guidance_read_version"] == 2  # 读毕对齐


def test_actor_guidance_gate_false_zero_injection(tmp_path):
    """版本差=0：不调指引、不写对齐版本、round_output 不变。"""
    docs = _docs(tmp_path)
    model = ScriptedModel(["actor 产出文本"])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(_state("auto", notes_version=2, read=2), _cfg())

    assert len(model.calls) == 1
    assert updates["turn_end_payload"]["round_output"] == "actor 产出文本"
    assert "guidance_read_version" not in updates


def test_actor_ask_mode_emits_guidance_question_breakpoint(tmp_path):
    """13 票：guidance_mode=ask 发四选 question 断点（spec L208 本义回填）。

    版本门通过 → 不再贴 [指引询问] 前缀，改发 question 断点；
    版本对齐照写；答案下轮由 actor 起手解释（见 test_teach_me.py）。
    """
    docs = _docs(tmp_path)
    model = ScriptedModel(["actor 产出文本"])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(_state("ask"), _cfg())
    assert updates["turn_end_reason"] == "question"
    payload = updates["turn_end_payload"]
    assert payload["question_text"] == "本轮讲解 —— 要为这轮的产出配一段讲解吗？"
    assert len(payload["options"]) == 4
    assert payload["options"][3] == "以后都深度教学 —— 之后每轮自动生成教学页，不再询问"
    assert payload["asker"] == "actor"
    assert updates["awaiting_input_from"] == "actor"
    assert updates["guidance_read_version"] == 2  # 读毕对齐照写
    assert len(model.calls) == 1  # 只 actor 本体调用：指引文本此刻不生成


def test_actor_ask_mode_teach_me_always_generates_page(tmp_path):
    """teach_me_pref=always（ask 模式决议过"以后都"）：直接 teach-me 不再询问。"""
    docs = _docs(tmp_path)
    model = ScriptedModel(["actor 产出文本", "<html>教学页</html>"])
    node = make_actor_node(model, shared_docs=docs)
    state = _state("ask")
    state["teach_me_pref"] = "always"
    updates = node(state, _cfg())
    assert updates["turn_end_reason"] == "round"
    assert "教学页已生成：teach-me/R3/index.html" in updates["turn_end_payload"][
        "round_output"
    ]
    teach_calls = [call for call in model.calls if call["role"] == "ask_agent"]
    assert len(teach_calls) == 1
    material = teach_calls[0]["messages"][0]["content"]
    assert "页面式深度教学" in material  # teach-me skill body 注入


def test_actor_guidance_off_zero_guidance(tmp_path):
    """off（及其他模式）：零指引调用零对齐写。"""
    docs = _docs(tmp_path)
    model = ScriptedModel(["actor 产出文本"])
    node = make_actor_node(model, shared_docs=docs)
    updates = node(_state("off"), _cfg())
    assert len(model.calls) == 1
    assert updates["turn_end_payload"]["round_output"] == "actor 产出文本"
    assert "guidance_read_version" not in updates


def test_actor_guidance_isolation_redline_excludes_mainline_history(tmp_path):
    """隔离红线：seed 主线历史独特标记 → ask_agent 调用材料绝不出现该标记。"""
    docs = _docs(tmp_path)
    model = ScriptedModel(["actor 产出文本", GUIDANCE_TEXT])
    node = make_actor_node(model, shared_docs=docs)
    state = _state("auto")
    from langchain_core.messages import AIMessage, HumanMessage

    state["actor_messages"] = [
        HumanMessage(content=ACTOR_MARKER),
        AIMessage(content=ACTOR_MARKER),
    ]
    state["demo_messages"] = [HumanMessage(content=DEMO_MARKER)]
    node(state, _cfg())

    ask_calls = [call for call in model.calls if call["role"] == "ask_agent"]
    assert len(ask_calls) == 1
    material = ask_calls[0]["messages"][0]["content"]
    assert ACTOR_MARKER not in material
    assert DEMO_MARKER not in material
