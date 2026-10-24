"""context_assembler 节点（05 终裁 6 → 09 工厂化）：assembled_context 组装。

09 票：make_assembler_node(shared_docs) 工厂——system 五段组装（base + 作用域
规则行 + todo 板渲染 + notepad 切片块 + 技能头块），新增 tools_subset/skills 键；
shared_docs 非 None 时版本门控注入 notepad 切片并对齐 guidance_read_version。
每轮整覆写（state key 无 reducer）；不写任何消息。
"""

from __future__ import annotations

from project_agent.nodes import make_assembler_node
from project_agent.shared_docs import SharedDocs
from project_agent.skills import skill_heads

SRC_SUBSET = sorted(
    {"FileRead", "Glob", "Grep", "FileWrite", "FileEdit", "Shell"}
)
SKILL_LINES = [f"{h.name}：{h.one_liner}" for h in skill_heads()]


def _state(**overrides) -> dict:
    base = {
        "task_brief": "x",
        "build_way": "way1",
        "guidance_mode": "auto",
        "current_scope": "src",
        "todos": [
            {"content": "梳理需求边界", "status": "completed"},
            {"content": "推进对话任务", "status": "in_progress"},
        ],
    }
    base.update(overrides)
    return base


def test_assembler_factory_composes_five_sections():
    """system 五段：base + 作用域规则行 + todo 板 + （无 notepad）+ 技能头块。"""
    node = make_assembler_node()  # shared_docs 缺省 None
    updates = node(_state(assembled_context={"system": "旧值", "todo_board": ["旧板"]}))
    ctx = updates["assembled_context"]
    # base 段（既有）
    assert "你是构建 agent" in ctx["system"]
    assert "当前方式 way1" in ctx["system"]
    assert "待办 1 项" in ctx["system"]  # 未清数：in_progress 计未清
    # 作用域规则行段
    assert "【作用域】当前在源码区：只关注代码文件的组织与实现细节。" in ctx["system"]
    # todo 板渲染段（三态逐行）
    assert "completed: 梳理需求边界" in ctx["system"]
    assert "in_progress: 推进对话任务" in ctx["system"]
    # 技能头块段（只注名字+一句话）
    assert "【技能】" in ctx["system"]
    for line in SKILL_LINES:
        assert line in ctx["system"]
    # shared_docs=None → 零 Notepad 块
    assert "【Notepad】" not in ctx["system"]
    # 整覆写：旧值全灭
    assert ctx != {"system": "旧值", "todo_board": ["旧板"]}
    assert ctx["todo_board"] == ["completed: 梳理需求边界", "in_progress: 推进对话任务"]
    assert ctx["scope"] == "src"


def test_assembler_factory_new_keys_tools_subset_and_skills():
    """新键：tools_subset（sorted 交集）+ skills（name：one_liner 列表）。"""
    node = make_assembler_node()
    ctx = node(_state())["assembled_context"]
    assert set(ctx) == {"system", "todo_board", "scope", "tools_subset", "skills"}
    assert ctx["tools_subset"] == SRC_SUBSET
    assert ctx["skills"] == SKILL_LINES


def test_assembler_factory_scope_defaults_to_main():
    """current_scope 缺省 → main：main 规则行 + main 全工具子集。"""
    node = make_assembler_node()
    ctx = node({"build_way": "way1", "todos": []})["assembled_context"]
    assert ctx["scope"] == "main"
    assert "【作用域】当前为主工作区" in ctx["system"]
    from project_agent.tools.registry import ALL_TOOLS

    assert ctx["tools_subset"] == sorted(ALL_TOOLS)


def test_assembler_factory_system_mentions_pending_count_only():
    node = make_assembler_node()
    ctx = node(
        _state(
            guidance_mode="off",
            todos=[
                {"content": "a", "status": "completed"},
                {"content": "b", "status": "completed"},
                {"content": "c", "status": "pending"},
            ],
        )
    )["assembled_context"]
    assert "待办 1 项" in ctx["system"]  # 未清 1 项


def test_assembler_factory_writes_no_messages():
    updates = make_assembler_node()({})
    assert "actor_messages" not in updates
    assert "demo_messages" not in updates


def test_assembler_factory_empty_todos_render_empty_board():
    ctx = make_assembler_node()({"build_way": "way1", "todos": []})["assembled_context"]
    assert ctx["todo_board"] == []


# —— 09 验收 6：notepad 切片版本门 ——


def test_assembler_notepad_gate_open_injects_entries_and_aligns(tmp_path):
    """门真（版本差>0）→ 【Notepad】块注入全部条目 + guidance_read_version 对齐。"""
    docs = SharedDocs(tmp_path)
    docs.notepad_add(1, "登录页要用浅色主题")
    docs.notepad_add(2, "接口超时需设 30 秒")
    node = make_assembler_node(shared_docs=docs)
    updates = node(_state(notes_version=2, guidance_read_version=0))
    system = updates["assembled_context"]["system"]
    assert "【Notepad】" in system
    assert "【R1】- 登录页要用浅色主题" in system
    assert "【R2】- 接口超时需设 30 秒" in system
    # 节点写对齐：下轮差=0 不再注入（stale-read 杜绝）
    assert updates["guidance_read_version"] == 2


def test_assembler_notepad_gate_closed_no_block_no_write(tmp_path):
    """门假（差=0）→ 零 Notepad 块零版本写。"""
    docs = SharedDocs(tmp_path)
    docs.notepad_add(1, "甲")
    node = make_assembler_node(shared_docs=docs)
    updates = node(_state(notes_version=2, guidance_read_version=2))
    assert "【Notepad】" not in updates["assembled_context"]["system"]
    assert "guidance_read_version" not in updates
    # notes_version=0（无键）差=0 → 同样门关
    updates2 = node(_state())
    assert "【Notepad】" not in updates2["assembled_context"]["system"]
    assert "guidance_read_version" not in updates2


def test_assembler_shared_docs_none_only_assembled_context_key():
    """shared_docs=None → 零 Notepad 块零版本写（467 基线零回归）。"""
    updates = make_assembler_node()(_state(notes_version=5, guidance_read_version=0))
    assert set(updates) == {"assembled_context"}
    assert "【Notepad】" not in updates["assembled_context"]["system"]


def test_assembler_system_changes_with_scope_and_note_version(tmp_path):
    """两轮不同 scope / notepad 版本 → system 不同（动态组装的材料基础）。"""
    docs = SharedDocs(tmp_path)
    node = make_assembler_node(shared_docs=docs)
    sys_main = node(_state(current_scope="main"))["assembled_context"]["system"]
    docs.notepad_add(1, "甲")
    sys_src_open = node(
        _state(current_scope="src", notes_version=1)
    )["assembled_context"]["system"]
    sys_src_closed = node(_state(current_scope="src", notes_version=1,
                                 guidance_read_version=1))["assembled_context"]["system"]
    assert sys_main != sys_src_open != sys_src_closed
