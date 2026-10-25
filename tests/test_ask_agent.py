"""10 票切片 1：AskAgent 模块（工具面/旁路上下文/独立历史/材料包/链接验证）。"""

from __future__ import annotations

from project_agent.ask_agent import (
    ASK_TOOLSET,
    AskBypass,
    ask_answer,
    build_ask_context,
    build_guidance,
    guidance_material_pack,
    verify_link,
)
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel

FORBIDDEN = ("FileWrite", "FileEdit", "Shell", "TodoWrite", "DocScaffold")


def _docs(tmp_path) -> SharedDocs:
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "第一轮：定下技术栈 React")
    docs.append_round_entry(2, "第二轮：接口用 REST")
    docs.notepad_add(1, "浅色主题")
    docs.notepad_add(2, "错误码五位")
    return docs


# —— 验收 5：工具面 = 矩阵只读集 ——


def test_ask_toolset_is_matrix_read_only_set():
    assert len(ASK_TOOLSET) == 10
    for tool in FORBIDDEN:
        assert tool not in ASK_TOOLSET
    assert "FileRead" in ASK_TOOLSET
    assert "Grep" in ASK_TOOLSET
    assert "WebFetch" in ASK_TOOLSET


# —— 验收 1：旁路上下文直读磁盘切片（非主线历史）——


def test_build_ask_context_reads_disk_doc_slices(tmp_path):
    context = build_ask_context(_docs(tmp_path), "技术栈是什么？")
    assert len(context) == 1
    assert context[0]["role"] == "user"
    content = context[0]["content"]
    assert "【R1】第一轮：定下技术栈 React" in content
    assert "【R2】第二轮：接口用 REST" in content
    assert "问题：技术栈是什么？" in content


def test_build_ask_context_without_shared_docs_is_bare_question():
    assert build_ask_context(None, "什么是构建方式？") == [
        {"role": "user", "content": "什么是构建方式？"}
    ]


def test_ask_answer_returns_text_and_accumulated_history(tmp_path):
    model = ScriptedModel(["用 React。", "用 REST。"])
    history: list[dict] = [{"role": "user", "content": "旧问"}, {"role": "assistant", "content": "旧答"}]
    text, new_history = ask_answer(
        model, _docs(tmp_path), "前端用什么？", history=history, thread_id="t-ask"
    )
    assert text == "用 React。"
    assert model.calls[0]["role"] == "ask_agent"
    assert model.calls[0]["thread_id"] == "t-ask"
    msgs = model.calls[0]["messages"]
    assert msgs[:2] == history  # 独立历史在前
    assert "问题：前端用什么？" in msgs[2]["content"]
    assert new_history[-1] == {"role": "assistant", "content": "用 React。"}
    assert history == [{"role": "user", "content": "旧问"}, {"role": "assistant", "content": "旧答"}]

    # 追问：历史自累积（第二次调用携带上轮 Q/A）
    text2, new_history2 = ask_answer(
        model, _docs(tmp_path), "后端呢？", history=new_history, thread_id="t-ask"
    )
    assert text2 == "用 REST。"
    second = model.calls[1]["messages"]
    assert second[: len(new_history) - 1] == new_history[:-1]
    assert "问题：后端呢？" in second[-1]["content"]


def test_ask_bypass_accumulates_history(tmp_path):
    model = ScriptedModel(["答一", "答二"])
    bypass = AskBypass(model, _docs(tmp_path), "t-bypass")
    assert bypass.history == []
    assert bypass.ask("问一") == "答一"
    assert bypass.ask("问二") == "答二"
    assert len(bypass.history) == 4  # 两轮各 context+answer
    assert bypass.history[1] == {"role": "assistant", "content": "答一"}
    assert bypass.history[-1] == {"role": "assistant", "content": "答二"}
    # 第二次调用 messages 含第一轮问答（独立线程历史自累积）
    second = model.calls[1]["messages"]
    assert any(m["content"] == "答一" for m in second)
    assert "问题：问二" in second[-1]["content"]


# —— 验收 6：为什么 + 下一步 + 技术栈文档 + 死链拒 ——


def test_guidance_material_pack_has_reason_next_step_docs_and_notes(tmp_path):
    docs = _docs(tmp_path)
    pack = guidance_material_pack(
        round_summary="定下 React 技术栈",
        notes=docs.notepad_entries(),
        doc_slice=docs.read_round(1),
    )
    assert "为什么这么做：本轮 定下 React 技术栈" in pack
    assert "下一步：推进 todo 板" in pack
    assert "技术栈文档：" in pack
    assert "【R1】第一轮：定下技术栈 React" in pack
    assert "【R1】- 浅色主题" in pack
    assert "【R2】- 错误码五位" in pack


def test_build_guidance_single_shot_role_ask_agent(tmp_path):
    model = ScriptedModel(["指引：因为用了 React，下一步推进 todo 板。"])
    docs = _docs(tmp_path)
    text = build_guidance(
        model,
        round_summary="定下 React",
        notes=docs.notepad_entries(),
        doc_slice=docs.read_round(2),
        thread_id="t-guide",
    )
    assert text == "指引：因为用了 React，下一步推进 todo 板。"
    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["role"] == "ask_agent"
    assert call["thread_id"] == "t-guide"
    assert len(call["messages"]) == 1  # 材料包单发，无历史累积
    material = call["messages"][0]["content"]
    assert "为什么这么做" in material
    assert "下一步：推进 todo 板" in material


def test_verify_link_accepts_live_and_rejects_dead():
    def fetch(url: str) -> str | None:
        return "<html>ok</html>" if url == "https://ok.example" else None

    assert verify_link("https://ok.example", fetch) is True
    assert verify_link("https://dead.example", fetch) is False


def test_verify_link_rejects_empty_and_exception():
    assert verify_link("https://empty.example", lambda url: "") is False
    assert verify_link("https://none.example", lambda url: None) is False

    def boom(url: str) -> str | None:
        raise RuntimeError("network down")

    assert verify_link("https://boom.example", boom) is False
