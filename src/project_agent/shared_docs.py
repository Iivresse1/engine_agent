"""共享文档区（06 票，ADR-0004『磁盘文档为共享介质』）。

BUILD_LOG.md 轮次生成物 + NOTES.md 共享外部记忆（GLOSSARY『Notepad』）。
【R#】标记挂在每轮生成物前；切片检索按标记前缀切分——磁盘方案让检索
退化为纯文本处理。隔离红线（ADR-0002）：跨角色信息只经此共享文档区
交换，消息历史留各角色私有 key；版本门逻辑供 10 票 AskAgent 接线，
stale-read 被结构性杜绝。
"""

from __future__ import annotations

import re
from pathlib import Path

# 轮次标注行首（re.MULTILINE 下匹配每行行首的【R#】标记）
_ROUND_MARKER = re.compile(r"^【R(\d+)】", re.MULTILINE)
_NOTEPAD_ENTRY = re.compile(r"^【R(\d+)】- (.*)$", re.MULTILINE)

BUILD_LOG_FILENAME = "BUILD_LOG.md"
NOTEPAD_FILENAME = "NOTES.md"


class SharedDocs:
    """工作区共享文档区：root=工作区目录，测试用 tmp_path。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # —— 交付物落盘（07 票）——

    def write_deliverable(self, path_rel: str, content: str, *, way: str) -> bool:
        """写交付物：root/path_rel UTF-8 覆写，父目录 mkdir。

        白名单校验：path_rel ∈ DELIVERABLE_SETS[way]（未知 way → 空 → 全拒）；
        不在白名单 → 零写入零异常，返回 False（调用方记 round_end 提示）。
        """
        from project_agent.deliverables import deliverables_for

        if path_rel not in deliverables_for(way):
            return False
        path = self.root / path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True

    # —— DemoAgent 生成物（11 票：demo 文件名自由，无白名单）——

    def write_any(self, path_rel: str, content: str) -> bool:
        """写任意相对路径生成物（DemoAgent 专用）：root/path_rel UTF-8 覆写。

        无交付物白名单（ADR-0003：demo 文件自由命名）；安全底线只有一条：
        路径含 ".." → 零写入零异常，返回 False（不越出工作区）。
        """
        if not path_rel or ".." in path_rel:
            return False
        path = self.root / path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True

    # —— 轮次生成物（BUILD_LOG.md）——

    def append_round_entry(
        self, round_no: int, content: str, *, filename: str = BUILD_LOG_FILENAME
    ) -> None:
        """追加 "【R{round_no}】{content}\\n\\n"（条目间空行分隔；content 可多行）。"""
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"【R{round_no}】{content}\n\n")

    def read_rounds(
        self, *, filename: str = BUILD_LOG_FILENAME
    ) -> list[tuple[int, str]]:
        """解析全部条目：按 r"^【R(\\d+)】"（MULTILINE）切分，返回
        (round_no, 该轮全文含首行) 升序；文件不存在→[]。"""
        path = self.root / filename
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        matches = list(_ROUND_MARKER.finditer(text))
        entries: list[tuple[int, str]] = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            # 条目间空行是分隔符不属于该轮全文——rstrip 尾部空白
            entries.append((int(m.group(1)), text[m.start() : end].rstrip()))
        entries.sort(key=lambda entry: entry[0])
        return entries

    def read_round(
        self, round_no: int, *, filename: str = BUILD_LOG_FILENAME
    ) -> str | None:
        """切片检索：只返回该轮条目文本（含首行标记）；无→None。"""
        for no, content in self.read_rounds(filename=filename):
            if no == round_no:
                return content
        return None

    # —— Notepad（NOTES.md）——

    def notepad_add(self, round_no: int, content: str) -> None:
        """追加单行条目 "【R{round_no}】- {content}\\n"（content 不含换行，调用方保证）。"""
        path = self.root / NOTEPAD_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"【R{round_no}】- {content}\n")

    def notepad_entries(self) -> list[tuple[int, str]]:
        """全部条目 (round_no, content)；文件不存在→[]。"""
        path = self.root / NOTEPAD_FILENAME
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return [(int(m.group(1)), m.group(2)) for m in _NOTEPAD_ENTRY.finditer(text)]

    def notepad_read(self, *, round_no: int | None = None) -> list[tuple[int, str]]:
        """round_no=None→全部；否则只该轮切片（与 read_round 同套轮次切片机制）。"""
        entries = self.notepad_entries()
        if round_no is None:
            return entries
        return [(no, content) for no, content in entries if no == round_no]

    # —— 版本门（纯函数语义，方法形态）——

    def guidance_slice(
        self, notes_version: int, guidance_read_version: int
    ) -> list[tuple[int, str]]:
        """版本差>0→返回 notepad_entries()（全量，供注入）；差<=0→[]。"""
        if guidance_gate(notes_version, guidance_read_version):
            return self.notepad_entries()
        return []


def guidance_gate(notes_version: int, guidance_read_version: int) -> bool:
    """版本门（纯函数，供 10 票 AskAgent 接线）：差>0→True（注入）。"""
    return notes_version - guidance_read_version > 0


def align_guidance_read(notes_version: int) -> int:
    """消费后对齐：返回新 guidance_read_version（=notes_version）。"""
    return notes_version
