"""SharedDocs（06 票）：【R#】轮次标记、按轮切片检索、Notepad 共享外部记忆。

磁盘为共享事实来源（ADR-0004）：切片检索退化为纯文本处理；
Notepad（GLOSSARY）＝工作区共享外部记忆，全角色可读写，条目带【R#】。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_agent.shared_docs import SharedDocs, align_guidance_read, guidance_gate

# —— BUILD_LOG 轮次生成物：不存在 → [] ——

def test_read_rounds_empty_when_file_missing(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    assert docs.read_rounds() == []
    assert docs.read_round(1) is None


def test_notepad_empty_when_file_missing(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    assert docs.notepad_entries() == []
    assert docs.notepad_read() == []
    assert docs.notepad_read(round_no=1) == []


# —— append_round_entry 落盘格式 ——

def test_append_round_entry_writes_marker_and_blank_separator(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "第一轮产出")
    raw = (tmp_path / "BUILD_LOG.md").read_text(encoding="utf-8")
    assert raw == "【R1】第一轮产出\n\n"


def test_append_round_entry_custom_filename(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "甲", filename="OTHER.md")
    assert docs.read_rounds() == []
    assert docs.read_rounds(filename="OTHER.md") == [(1, "【R1】甲")]


def test_append_creates_missing_parent_directories(tmp_path: Path):
    docs = SharedDocs(tmp_path / "nested" / "ws")
    docs.append_round_entry(1, "甲")
    docs.notepad_add(1, "注记")
    assert docs.read_rounds() == [(1, "【R1】甲")]
    assert docs.notepad_entries() == [(1, "注记")]


# —— read_rounds 解析：表驱动（多行条目按下一标记切分是重点）——

@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([(1, "甲")], [(1, "【R1】甲")]),
        ([(1, "甲"), (2, "乙")], [(1, "【R1】甲"), (2, "【R2】乙")]),
        # 乱序写入：返回仍按 round_no 升序
        ([(2, "乙"), (1, "甲")], [(1, "【R1】甲"), (2, "【R2】乙")]),
        # 多行条目：正文跨行，按下一标记切分、全文含首行
        (
            [(1, "标题\n正文甲\n正文乙"), (2, "次轮")],
            [(1, "【R1】标题\n正文甲\n正文乙"), (2, "【R2】次轮")],
        ),
        # 同轮多条追加（重规划后同号续写）
        (
            [(1, "先写"), (2, "中写"), (1, "后写")],
            [(1, "【R1】先写"), (1, "【R1】后写"), (2, "【R2】中写")],
        ),
    ],
    ids=["single", "two", "out-of-order", "multiline", "same-round-twice"],
)
def test_read_rounds_table_driven(
    tmp_path: Path,
    entries: list[tuple[int, str]],
    expected: list[tuple[int, str]],
):
    docs = SharedDocs(tmp_path)
    for no, content in entries:
        docs.append_round_entry(no, content)
    assert docs.read_rounds() == expected


# —— read_round 切片检索：只返回该轮 ——

def test_read_round_returns_only_that_round(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "甲")
    docs.append_round_entry(2, "乙")
    docs.append_round_entry(3, "丙")
    assert docs.read_round(2) == "【R2】乙"
    assert docs.read_round(9) is None


def test_read_round_multiline_slice_returns_full_round_text(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "计划\n一\n二")
    docs.append_round_entry(2, "收尾")
    assert docs.read_round(1) == "【R1】计划\n一\n二"
    assert docs.read_round(2) == "【R2】收尾"


def test_read_round_same_number_returns_first_slice(tmp_path: Path):
    """同轮多条：切片检索取首个（BUILD_LOG 连续编号为常态，此为边界钉定）。"""
    docs = SharedDocs(tmp_path)
    docs.append_round_entry(1, "先写")
    docs.append_round_entry(1, "后写")
    assert docs.read_round(1) == "【R1】先写"


# —— Notepad（NOTES.md）——

def test_notepad_add_writes_single_line_entry_with_marker(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.notepad_add(1, "错误猜想甲")
    raw = (tmp_path / "NOTES.md").read_text(encoding="utf-8")
    assert raw == "【R1】- 错误猜想甲\n"


def test_notepad_entries_parses_all_in_written_order(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.notepad_add(1, "甲")
    docs.notepad_add(2, "乙")
    docs.notepad_add(2, "丙")
    assert docs.notepad_entries() == [(1, "甲"), (2, "乙"), (2, "丙")]


def test_notepad_read_round_slice_only_that_round(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.notepad_add(1, "甲")
    docs.notepad_add(2, "乙")
    docs.notepad_add(2, "丙")
    assert docs.notepad_read(round_no=2) == [(2, "乙"), (2, "丙")]
    assert docs.notepad_read(round_no=3) == []
    assert docs.notepad_read() == [(1, "甲"), (2, "乙"), (2, "丙")]


# —— guidance_slice（方法形态的版本门入口）——

def test_guidance_slice_injects_only_when_version_gap_positive(tmp_path: Path):
    docs = SharedDocs(tmp_path)
    docs.notepad_add(1, "甲")
    assert docs.guidance_slice(notes_version=1, guidance_read_version=0) == [(1, "甲")]
    assert docs.guidance_slice(notes_version=1, guidance_read_version=1) == []
    assert docs.guidance_slice(notes_version=0, guidance_read_version=1) == []


# —— 版本门纯函数（模块级，供 10 票 AskAgent 接线）——

@pytest.mark.parametrize(
    ("notes_version", "guidance_read_version", "expected"),
    [
        (0, 0, False),  # 初始：无新内容不注入
        (1, 0, True),  # 差>0：注入
        (2, 1, True),
        (1, 1, False),  # 已对齐：不重复注入
        (5, 5, False),
        (0, 1, False),  # 读超写（防御）：不注入
    ],
)
def test_guidance_gate_table_driven(
    notes_version: int, guidance_read_version: int, expected: bool
):
    assert guidance_gate(notes_version, guidance_read_version) is expected


@pytest.mark.parametrize("notes_version", [0, 1, 5])
def test_align_guidance_read_returns_notes_version(notes_version: int):
    assert align_guidance_read(notes_version) == notes_version


def test_write_inject_align_no_reinject_reinject_sequence(tmp_path: Path):
    """验收 3 完整序（写 NOTE→摘要→AskAgent 读→对齐）：
    v=0,g=0→不注入→写一条(v=1)→注入→对齐 g=1→不重复注入→
    再写一条(v=2)→新内容再注入。
    """
    docs = SharedDocs(tmp_path)
    v, g = 0, 0
    assert guidance_gate(v, g) is False
    docs.notepad_add(1, "首个关键事实")  # NotepadAdd 成功 → notes_version 自增
    v = 1
    assert guidance_gate(v, g) is True  # 差>0：AskAgent 注入
    assert docs.guidance_slice(v, g) == [(1, "首个关键事实")]
    g = align_guidance_read(v)  # 消费后对齐
    assert g == 1
    assert guidance_gate(v, g) is False  # 不再重复注入
    assert docs.guidance_slice(v, g) == []
    docs.notepad_add(2, "第二个关键事实")  # 再写一条
    v = 2
    assert guidance_gate(v, g) is True  # 新内容再注入
    assert docs.guidance_slice(v, g) == [(1, "首个关键事实"), (2, "第二个关键事实")]
