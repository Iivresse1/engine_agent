"""09 票图级三联：动态组装 / 工具子集 / notepad 版本门（验收 1/2/6）。

tmp 工作区 + ScriptedModel + graph workspace_root 双注入（assembler+actor 同源
SharedDocs）：
- 第一轮 scope=main：假模型收到的 system 含 main 规则 + 全 15 件工具清单；
- 第二轮输入带 current_scope="src"：system 含 src 规则 + 6 件工具子集；
- notepad 写两条（notes_version=2）→ 下一轮 system 含【Notepad】块且
  guidance_read_version 对齐=2 → 再下一轮零 Notepad 块（版本门关）。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from project_agent.graph import build_graph
from project_agent.tools.registry import ALL_TOOLS
from tests.doubles.fake_model import ScriptedModel

TWO_PENDING = [
    {"content": "梳理需求边界", "status": "pending"},
    {"content": "推进对话任务", "status": "pending"},
]

MAIN_RULE = "【作用域】当前为主工作区：优先推进待办；工具面向构建与文件读写。"
SRC_RULE = "【作用域】当前在源码区：只关注代码文件的组织与实现细节。"
SRC_TOOLS = "【可用工具】FileEdit、FileRead、FileWrite、Glob、Grep、Shell"
MAIN_TOOLS = f"【可用工具】{'、'.join(sorted(ALL_TOOLS))}"

R1_NOTE = "推进中。记录：登录页要用浅色主题"
R2_NOTE = "继续。记录：接口超时需设 30 秒。记录：错误码统一 5 位"
R3 = "第三轮推进"
R4 = "第四轮推进"
R5 = "第五轮推进"


def _say(text: str, **extra) -> dict:
    payload = {"actor_messages": [HumanMessage(content=text)]}
    payload.update(extra)
    return payload


def _cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def _seed() -> dict:
    return {
        "task_brief": "想法",
        "build_way": "way1",
        "todos": TWO_PENDING,
        "actor_messages": [HumanMessage(content="开始")],
    }


def _actor_system(model, call_index: int) -> str:
    call = model.calls[call_index]
    assert call["role"] == "actor"
    assert call["messages"][0]["role"] == "system"
    return call["messages"][0]["content"]


def test_graph_dynamic_system_and_tools_subset_across_scopes(tmp_path: Path):
    """验收 1/2：system 动态组装 + 工具为作用域裁剪后子集（system 尾行断言）。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            R1_NOTE,  # 轮 1 actor（scope=main，写 1 条 note）
            "task_complete: false",
            R2_NOTE,  # 轮 2 actor（scope=src，写 2 条 note）
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-scope-09")

    # 轮 1：scope=main → system 含 main 规则 + 全工具清单
    r1 = app.invoke(_seed(), cfg)
    sys1 = _actor_system(model, 0)
    assert MAIN_RULE in sys1
    assert sys1.endswith(MAIN_TOOLS)
    assert r1["assembled_context"]["scope"] == "main"
    assert r1["assembled_context"]["tools_subset"] == sorted(ALL_TOOLS)
    assert r1["notes_version"] == 1
    # 既有断言面保持：round 断点正常
    assert r1["turn_end_reason"] == "round"

    # 轮 2：invoke 输入带 current_scope="src" → system 含 src 规则 + 6 件子集
    r2 = app.invoke(_say("继续", current_scope="src"), cfg)
    sys2 = _actor_system(model, 2)
    assert SRC_RULE in sys2
    assert MAIN_RULE not in sys2
    assert sys2.endswith(SRC_TOOLS)
    assert r2["assembled_context"]["scope"] == "src"
    assert r2["assembled_context"]["tools_subset"] == sorted(
        {"FileRead", "Glob", "Grep", "FileWrite", "FileEdit", "Shell"}
    )
    # 两轮 system 不同（动态组装，验收 2）
    assert sys1 != sys2
    assert r2["notes_version"] == 3


def test_graph_notepad_version_gate_three_rounds(tmp_path: Path):
    """验收 6：版本门三段——门开注入+对齐 → 门关零块。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            R1_NOTE,  # 轮 1：写 1 条 note（notes_version 0→1）——门差=1 于轮 2 开
            "task_complete: false",
            R3,  # 轮 2：无 note（门开——上轮写入的 1 条注入）
            "task_complete: false",
            R4,  # 轮 3：无 note（门关——零 Notepad 块）
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-gate-09")

    # 轮 1：Notepad 空，门差=0 → 轮 1 system 即零块
    r1 = app.invoke(_seed(), cfg)
    sys1 = _actor_system(model, 0)
    assert "【Notepad】" not in sys1
    assert r1["notes_version"] == 1

    # 轮 2：门差=1（notes_version=1 > guidance_read_version=0）→【Notepad】块
    # 注入 + guidance_read_version 对齐=1
    r2 = app.invoke(_say("继续"), cfg)
    sys2 = _actor_system(model, 2)
    assert "【Notepad】" in sys2
    assert "【R1】- 登录页要用浅色主题" in sys2
    assert r2["guidance_read_version"] == 1

    # 轮 3：差=0 → 门关，零 Notepad 块（stale-read 杜绝）
    r3 = app.invoke(_say("再继续"), cfg)
    sys3 = _actor_system(model, 4)
    assert "【Notepad】" not in sys3


def test_graph_notepad_two_notes_full_injection_and_alignment(tmp_path: Path):
    """验收 6（票面原文场景）：notepad 写两条（notes_version=2）→ 下一轮
    system 含【Notepad】块（两条全注入）且对齐=2 → 再下一轮零块。"""
    saver = InMemorySaver()
    model = ScriptedModel(
        [
            R1_NOTE,  # 轮 1：1 条（notes_version=1）——轮 2 注入 1 条并对齐=1
            "task_complete: false",
            R2_NOTE,  # 轮 2：2 条（notes_version 1→3）——轮 3 注入 3 条并对齐=3
            "task_complete: false",
            R3,  # 轮 3：无新 note——差=0 零块
            "task_complete: false",
            R4,  # 轮 4：无新 note——差=0 零块（脚本补位）
            "task_complete: false",
        ]
    )
    app = build_graph(checkpointer=saver, model=model, workspace_root=tmp_path)
    cfg = _cfg("g-gate2-09")

    app.invoke(_seed(), cfg)  # 轮 1
    # 轮 2：门开（差=1）→ 注入全部条目（1 条）+ 对齐
    r2 = app.invoke(_say("继续"), cfg)
    sys2 = _actor_system(model, 2)
    assert "【Notepad】" in sys2
    assert "【R1】- 登录页要用浅色主题" in sys2
    assert r2["guidance_read_version"] == 1
    # 轮 3：上轮写 2 条（notes_version=3 > read=1）→ 门再开：全量 3 条注入 + 对齐=3
    r3 = app.invoke(_say("再继续"), cfg)
    sys3 = _actor_system(model, 4)
    assert "【Notepad】" in sys3
    assert "【R1】- 登录页要用浅色主题" in sys3
    assert "【R2】- 接口超时需设 30 秒。" in sys3
    assert "【R2】- 错误码统一 5 位" in sys3
    assert r3["guidance_read_version"] == 3
    # 轮 4：差=0 → 门关零块
    r4 = app.invoke(_say("第四轮"), cfg)
    sys4 = _actor_system(model, 6)
    assert "【Notepad】" not in sys4
