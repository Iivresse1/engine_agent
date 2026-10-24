"""07 票切片 5：way4 三方案并行节点 + 入口路由新行 + 决议/重发/兜底。

- make_proposals_node(model)：prompt 含 task_brief+user_mode，要求输出三行
  "方案名|一句话摘要" → proposal_set: list[str]（≤3 行）；解析失败/空 →
  兜底三案 ["轻量方案：默认技术栈", "均衡方案：常用技术栈", "完整方案：企业级技术栈"]
- 写 proposal_set + turn_end_reason=choice:proposal +
  validate_payload(CHOICE_PROPOSAL, {"proposal_summaries": proposal_set})
- 决议消费：序号（裸/语境，同 02 的 _interpret 序法）→ selected_proposal=idx；
  关键词匹配方案文本（"轻量"→0 / "均衡"→1 / "完整"→2）；融合文本无匹配 →
  复用上轮 payload 重发（零 model 调用）
- 入口路由新行（行 3 前）：way4+selected_proposal 未设+todos 未设 → PROPOSALS
- 图接线：PROPOSALS→END（断点收轮）
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.nodes import make_proposals_node
from project_agent.routing import ENTRY_TRUTH_TABLE, PROPOSALS, entry_route
from tests.doubles.fake_model import ScriptedModel

FALLBACK_PROPOSALS = [
    "轻量方案：默认技术栈",
    "均衡方案：常用技术栈",
    "完整方案：企业级技术栈",
]


def _cfg(thread: str = "t-prop") -> dict:
    return {"configurable": {"thread_id": thread}}


def _resolve(state: dict, text: str) -> dict:
    return {"resolution_inputs": [*(state.get("resolution_inputs") or []), text]}


# —— 入口路由新行 ——


def test_entry_route_way4_without_selected_proposal_and_todos_to_proposals():
    """行序（行 3 前）：way4+selected_proposal 未设+todos 未设 → PROPOSALS。"""
    assert (
        entry_route({"task_brief": "x", "build_way": "way4", "todos": []}) == PROPOSALS
    )


def test_entry_route_way4_with_selected_proposal_falls_to_planner():
    """selected_proposal 已设 → 落到行 3 照旧（todos 空→PLANNER）。"""
    assert (
        entry_route(
            {"task_brief": "x", "build_way": "way4", "selected_proposal": 0, "todos": []}
        )
        == "planner"
    )


def test_entry_route_non_way4_skips_proposals():
    """非 way4（way1/2/3）：不命中 PROPOSALS 行——todos 空→PLANNER 照旧。"""
    for way in ("way1", "way2", "way3"):
        assert entry_route({"task_brief": "x", "build_way": way, "todos": []}) == "planner"


def test_entry_route_way4_todos_set_not_proposals():
    """todos 已设（非空）→ 不命中 PROPOSALS（未清→assembler 照旧）。"""
    assert (
        entry_route(
            {
                "task_brief": "x",
                "build_way": "way4",
                "todos": [{"content": "t", "status": "pending"}],
            }
        )
        == "context_assembler"
    )


def test_entry_truth_table_contains_proposals_row():
    """ENTRY_TRUTH_TABLE 加行：way4 未选方案 → PROPOSALS。"""
    rows = [(dashboard, target) for dashboard, target in ENTRY_TRUTH_TABLE]
    assert ({"task_brief": "x", "build_way": "way4"}, PROPOSALS) in rows


def test_entry_route_priority_proposals_before_planner():
    """优先级：PROPOSALS 行在 todos 判定之前（way4 未选时 todos 空不落 planner）。"""
    assert (
        entry_route({"task_brief": "x", "build_way": "way4", "todos": []}) != "planner"
    )


# —— 节点：提案产出 ——


def test_proposals_node_model_contract():
    """模型路径：role=actor、thread_id 出 config、prompt 含简报+用户基础。"""
    model = ScriptedModel(["轻量版|默认栈快起步\n均衡版|常用栈\n完整版|企业级栈"])
    node = make_proposals_node(model)
    state = {"task_brief": "记账工具", "user_mode": "novice", "resolution_inputs": []}
    updates = node(state, {"configurable": {"thread_id": "th-7"}})
    assert model.calls[0]["role"] == "actor"
    assert model.calls[0]["thread_id"] == "th-7"
    prompt = model.calls[0]["messages"][0]["content"]
    assert "任务简报" in prompt and "记账工具" in prompt
    assert "用户编程基础" in prompt or "user_mode" in prompt or "novice" in prompt
    assert updates["turn_end_reason"] == "choice:proposal"
    assert updates["proposal_set"] == [
        "轻量版|默认栈快起步",
        "均衡版|常用栈",
        "完整版|企业级栈",
    ]
    payload = updates["turn_end_payload"]
    assert payload["proposal_summaries"] == updates["proposal_set"]
    assert set(payload) == {"proposal_summaries"}  # 受控形状


def test_proposals_node_parses_three_lines_with_pipe():
    """三行"方案名|摘要" → proposal_set 三元素。"""
    model = ScriptedModel(["轻量|快\n均衡|中\n完整|全"])
    node = make_proposals_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert updates["proposal_set"] == ["轻量|快", "均衡|中", "完整|全"]


def test_proposals_node_caps_at_three_lines():
    """超过 3 行 → 截前 3（≤3 行）。"""
    model = ScriptedModel(["甲|1\n乙|2\n丙|3\n丁|4"])
    node = make_proposals_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert updates["proposal_set"] == ["甲|1", "乙|2", "丙|3"]


def test_proposals_node_model_none_falls_back():
    """model=None → 静态兜底三案（零 model 调用）。"""
    node = make_proposals_node(None)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert updates["proposal_set"] == FALLBACK_PROPOSALS
    assert updates["turn_end_reason"] == "choice:proposal"
    assert updates["turn_end_payload"]["proposal_summaries"] == FALLBACK_PROPOSALS


def test_proposals_node_garbage_output_falls_back():
    """解析失败/空行 → 兜底三案。"""
    model = ScriptedModel(["嗯随便说点什么"])
    node = make_proposals_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert updates["proposal_set"] == FALLBACK_PROPOSALS


def test_proposals_node_empty_output_falls_back():
    model = ScriptedModel(["   \n  \n"])
    node = make_proposals_node(model)
    updates = node({"task_brief": "x", "resolution_inputs": []})
    assert updates["proposal_set"] == FALLBACK_PROPOSALS


def test_proposals_node_reentry_with_selected_returns_empty():
    """可重入：selected_proposal 已设 → {}（零副作用）。"""
    node = make_proposals_node(None)
    assert node({"selected_proposal": 1}) == {}


# —— 决议消费 ——


def test_proposals_resolution_by_bare_index():
    """序号（裸）："2" → selected_proposal=1；round_end("方案已选定：{摘要}")。"""
    node = make_proposals_node(None)
    state = {
        "task_brief": "x",
        "proposal_set": FALLBACK_PROPOSALS,
        "resolution_inputs": ["2"],
        "turn_end_payload": {"proposal_summaries": FALLBACK_PROPOSALS},
    }
    updates = node(state)
    assert updates["selected_proposal"] == 1
    assert updates["resolution_inputs"] == []
    assert updates["turn_end_reason"] == "round"
    assert "方案已选定" in updates["turn_end_payload"]["round_output"]
    assert FALLBACK_PROPOSALS[1] in updates["turn_end_payload"]["round_output"]


def test_proposals_resolution_by_contextual_index():
    """语境序号："选第 3 个" / "方案 1" → idx。"""
    node = make_proposals_node(None)
    for text, expected in [("选第 3 个", 2), ("方案 1", 0), ("选项 2", 1)]:
        state = {
            "task_brief": "x",
            "proposal_set": FALLBACK_PROPOSALS,
            "resolution_inputs": [text],
            "turn_end_payload": {"proposal_summaries": FALLBACK_PROPOSALS},
        }
        updates = node(state)
        assert updates["selected_proposal"] == expected, text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("轻量", 0),
        ("就要均衡的", 1),
        ("完整方案", 2),
    ],
    ids=["light", "balanced", "full"],
)
def test_proposals_resolution_by_keyword(text, expected):
    """关键词匹配方案文本："轻量"→0 / "均衡"→1 / "完整"→2（含兜底案名）。"""
    node = make_proposals_node(None)
    state = {
        "task_brief": "x",
        "proposal_set": FALLBACK_PROPOSALS,
        "resolution_inputs": [text],
        "turn_end_payload": {"proposal_summaries": FALLBACK_PROPOSALS},
    }
    updates = node(state)
    assert updates["selected_proposal"] == expected


def test_proposals_resolution_keyword_matches_custom_proposals():
    """关键词按用户文本命中（idx 与位置绑定），proposal_set 用自定义文本做摘要。"""
    node = make_proposals_node(None)
    proposals = ["极简小工具|单文件", "标准工具|包管理", "企业平台|服务化"]
    state = {
        "task_brief": "x",
        "proposal_set": proposals,
        "resolution_inputs": ["完整"],
        "turn_end_payload": {"proposal_summaries": proposals},
    }
    updates = node(state)
    assert updates["selected_proposal"] == 2
    assert "方案已选定：企业平台|服务化" in updates["turn_end_payload"]["round_output"]


def test_proposals_resolution_uninterpretable_reshows_zero_model_calls():
    """融合文本无匹配 → 复用上轮 payload 重发（零 model 调用）。"""
    model = ScriptedModel(["轻量|快\n均衡|中\n完整|全"])  # 仅首次提案触模型
    node = make_proposals_node(model)
    first = node({"task_brief": "x", "resolution_inputs": []})
    assert len(model.calls) == 1

    state = {
        "task_brief": "x",
        "proposal_set": first["proposal_set"],
        "resolution_inputs": ["说不清要哪种"],
        "turn_end_payload": first["turn_end_payload"],
    }
    updates = node(state)
    assert updates["turn_end_reason"] == "choice:proposal"
    assert updates["turn_end_payload"] == first["turn_end_payload"]  # 复用重发
    assert updates["resolution_inputs"] == []
    assert len(model.calls) == 1  # 零重复调用


def test_proposals_resolution_without_valid_payload_regenerates_fallback():
    """上轮 payload 不可复用（缺失/形状不符）→ 兜底三案重发。"""
    node = make_proposals_node(None)
    state = {
        "task_brief": "x",
        "proposal_set": FALLBACK_PROPOSALS,
        "resolution_inputs": ["说不清"],
        "turn_end_payload": {},
    }
    updates = node(state)
    assert updates["turn_end_reason"] == "choice:proposal"
    assert updates["turn_end_payload"]["proposal_summaries"] == FALLBACK_PROPOSALS


# —— 图级：提案→断点→选定 ——


def test_graph_proposals_flow_with_route_and_breakpoint(tmp_path):
    """图级全链前半：way4 未选 → PROPOSALS 节点 → choice:proposal 断点 → END；
    决议输入（序号）→ selected_proposal 写定 + round_end。"""
    saver = InMemorySaver()
    model = ScriptedModel(["轻量|快\n均衡|中\n完整|全"])
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg("g-prop-1")

    seed = {
        "task_brief": "记账工具",
        "build_way": "way4",
        "user_mode": "experienced",
        "guidance_pref": "off",
        "decision_mode": "manual",
        "skill_packs": [],
        "todos": [],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "choice:proposal"
    assert r1["proposal_set"] == ["轻量|快", "均衡|中", "完整|全"]
    assert r1["turn_end_payload"]["proposal_summaries"] == r1["proposal_set"]
    assert "selected_proposal" not in r1

    # 决议：序号 3 → selected_proposal=2
    r2 = app.invoke(_resolve(r1, "3"), cfg)
    assert r2["selected_proposal"] == 2
    assert r2["resolution_inputs"] == []
    assert r2["turn_end_reason"] == "round"
    assert "方案已选定" in r2["turn_end_payload"]["round_output"]


def test_graph_proposals_keyword_fusion_flow():
    """图级：融合文本关键词（"均衡"）→ selected_proposal=1。"""
    saver = InMemorySaver()
    model = ScriptedModel(["轻量|快\n均衡|中\n完整|全"])
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg("g-prop-2")
    seed = {
        "task_brief": "x",
        "build_way": "way4",
        "todos": [],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    r2 = app.invoke(_resolve(r1, "均衡一点的"), cfg)
    assert r2["selected_proposal"] == 1


def test_graph_proposals_uninterpretable_reshows():
    """图级：无匹配 → 重发 choice:proposal（复用 payload，零 model 调用）。"""
    saver = InMemorySaver()
    model = ScriptedModel(["轻量|快\n均衡|中\n完整|全"])
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg("g-prop-3")
    seed = {
        "task_brief": "x",
        "build_way": "way4",
        "todos": [],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    calls_after_first = len(model.calls)
    r2 = app.invoke(_resolve(r1, "完全说不相关的话"), cfg)
    assert r2["turn_end_reason"] == "choice:proposal"
    assert r2["turn_end_payload"] == r1["turn_end_payload"]
    assert len(model.calls) == calls_after_first  # 零调用

    # 之后正常选定仍可推进
    r3 = app.invoke(_resolve(r2, "1"), cfg)
    assert r3["selected_proposal"] == 0


def test_graph_proposals_model_none_static_fallback_flow():
    """model=None：PROPOSALS 走静态兜底三案；选定照常。"""
    saver = InMemorySaver()
    app = build_graph(checkpointer=saver, model=None)
    cfg = _cfg("g-prop-4")
    seed = {
        "task_brief": "x",
        "build_way": "way4",
        "todos": [],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    assert r1["turn_end_reason"] == "choice:proposal"
    assert r1["proposal_set"] == FALLBACK_PROPOSALS

    r2 = app.invoke(_resolve(r1, "轻量"), cfg)
    assert r2["selected_proposal"] == 0
    assert r2["turn_end_reason"] == "round"


def test_graph_selected_proposal_set_routes_to_planner():
    """选定后：todos 空 → PLANNER（PROPOSALS 行不命中）——下轮出计划。"""
    saver = InMemorySaver()
    model = ScriptedModel(["轻量|快\n均衡|中\n完整|全"])
    app = build_graph(checkpointer=saver, model=model)
    cfg = _cfg("g-prop-5")
    seed = {
        "task_brief": "x",
        "build_way": "way4",
        "todos": [],
        "actor_messages": [HumanMessage(content="开始")],
    }
    r1 = app.invoke(seed, cfg)
    r2 = app.invoke(_resolve(r1, "1"), cfg)
    assert r2["turn_end_reason"] == "round"

    r3 = app.invoke({"actor_messages": [HumanMessage(content="继续")]}, cfg)
    # todos 空 + selected_proposal 已设 → planner 出计划（07 切片 6 深化项）
    assert "已列出" in r3["turn_end_payload"]["round_output"]
