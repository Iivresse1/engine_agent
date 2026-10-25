"""10 票切片 4：图级三联——旁路独立历史+磁盘切片 / 指引门控对齐 / 死链拒。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.ask_agent import AskBypass, guidance_material_pack, verify_link
from project_agent.graph import build_graph
from project_agent.repl import ReplHost
from project_agent.shared_docs import SharedDocs
from tests.doubles.fake_model import ScriptedModel
from tests.doubles.scripted_io import ScriptedIO

ACTOR_MARKER = "ACTOR_PRIVATE_MARKER_G10"
GUIDANCE_TEXT = "指引：因为用了 React，下一步推进 todo 板，文档 https://react.dev。"

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]


def _cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def _seed_state() -> dict:
    return {
        "task_brief": "记账 CLI",
        "build_way": "way1",
        "todos": list(TWO_PENDING),
        "actor_messages": [HumanMessage(content=ACTOR_MARKER)],
        "round_count": 2,
    }


def _docs(tmp_path) -> SharedDocs:
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "第一轮文档")
    docs.append_round_entry(2, "第二轮文档：React 技术栈")
    docs.notepad_add(1, "浅色主题")
    docs.notepad_add(2, "错误码五位")
    return docs


# —— 1. 旁路：独立 thread 历史自累积 + 磁盘切片作答（不进主图/不读主线历史）——


def test_graph_bypass_independent_history_and_doc_slice(tmp_path):
    main = ScriptedModel(
        [
            "完成：梳理需求边界",  # 工作轮 1 actor
            "task_complete: false",  # verifier
            "继续推进",  # 工作轮 2 actor（旁路之后）
            "task_complete: false",
        ]
    )
    ask_model = ScriptedModel(["旁路答一", "旁路答二"])
    docs = _docs(tmp_path)
    app = build_graph(checkpointer=InMemorySaver(), model=main, workspace_root=tmp_path)
    seeded = app.invoke(_seed_state(), _cfg("g-ask-1"))

    io = ScriptedIO(
        [
            "/ask-for-help 前端用什么？",
            "/ask-for-help 后端用什么？",
            "继续",
            "/exit",
        ]
    )
    host = ReplHost(
        app,
        io,
        "g-ask-1",
        shared_docs=docs,
        ask_bypass=AskBypass(ask_model, docs, "t-ask"),
    )
    host._last_state = dict(seeded)  # 模拟上一轮断点
    host.run()

    assert len(ask_model.calls) == 2
    first = ask_model.calls[0]["messages"]
    assert len(first) == 1  # 独立 history 起点：只有本轮上下文
    assert first[0]["role"] == "user"
    assert "【R3】完成：梳理需求边界" in first[0]["content"]  # 磁盘切片（非主线历史副本）
    assert ACTOR_MARKER not in first[0]["content"]  # 主线历史绝不进旁路
    # 追问上下文保持：第二轮 messages 含第一轮问答
    second = ask_model.calls[1]["messages"]
    assert second[0]["content"] == first[0]["content"]
    assert second[1] == {"role": "assistant", "content": "旁路答一"}
    assert "问题：后端用什么？" in second[2]["content"]

    # 图 state 零污染：旁路内容不进 actor_messages（两次提问后仍走一轮主图）
    final = app.get_state(_cfg("g-ask-1")).values
    texts = [
        getattr(message, "content", "")
        for message in final.get("actor_messages") or []
    ]
    assert "旁路答一" not in "\n".join(texts)
    assert "前端用什么？" not in "\n".join(texts)


# —— 2. 指引：版本门控注入 + 读毕对齐（对齐后同材料不再重复）——


def test_graph_guidance_gate_injects_once_then_aligned(tmp_path):
    model = ScriptedModel(
        [
            "完成：梳理需求边界。记录：新增约束",  # 工作轮 1 actor（本轮新增 NOTE → 差>0）
            GUIDANCE_TEXT,  # 图内指引（ask_agent）
            "task_complete: false",  # verifier
            "第二轮产出",  # 工作轮 2 actor（门已对齐）
            "task_complete: false",
        ]
    )
    docs = _docs(tmp_path)
    app = build_graph(checkpointer=InMemorySaver(), model=model, workspace_root=tmp_path)
    seed = _seed_state()
    # 入轮时已对齐（assembler 门差=0）；actor 本轮写 1 条 NOTE → notes_version 3，
    # 指引门差 3-2>0 → 注入并对齐到 3。次轮差=0 → 零重复注入。
    seed.update({"guidance_mode": "auto", "notes_version": 2, "guidance_read_version": 2})

    r1 = app.invoke(seed, _cfg("g-guide-1"))
    assert r1["turn_end_payload"]["round_output"].endswith(GUIDANCE_TEXT)
    assert r1["notes_version"] == 3
    assert r1["guidance_read_version"] == 3  # 节点写对齐
    # 主线私有 key 不被指引污染
    assert "指引" not in r1["round_summary"]

    ask_calls = [call for call in model.calls if call["role"] == "ask_agent"]
    assert len(ask_calls) == 1
    material = ask_calls[0]["messages"][0]["content"]
    assert "为什么这么做" in material
    assert "【R3】- 新增约束" in material
    assert "【R3】完成：梳理需求边界" in material
    assert ACTOR_MARKER not in material

    r2 = app.invoke({"actor_messages": [HumanMessage(content="继续")]}, _cfg("g-guide-1"))
    assert r2["guidance_read_version"] == 3
    assert r2["turn_end_payload"]["round_output"] == "第二轮产出"  # 门已对齐零重复注入
    assert len([call for call in model.calls if call["role"] == "ask_agent"]) == 1


# —— 3. 死链拒：假 fetch 预置死链被拒，活链通过 ——


def test_graph_guidance_dead_link_rejected_by_verify_link():
    def fetch(url: str) -> str | None:
        return "<html>live</html>" if url == "https://react.dev" else None

    assert verify_link("https://react.dev", fetch) is True
    assert verify_link("https://dead.example/gone", fetch) is False
    assert verify_link("https://react.dev", lambda url: None) is False

    pack = guidance_material_pack(
        round_summary="定下 React",
        notes=[],
        doc_slice="技术栈文档：https://react.dev\n参考：https://dead.example/gone",
    )
    assert "https://react.dev" in pack
    assert "https://dead.example/gone" in pack  # 材料包原样；有效性由 verify_link 裁决
