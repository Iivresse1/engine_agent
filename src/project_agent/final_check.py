"""终检管线（12 票）：标记剥离 + 确定性 diff + 语义校验 + 双份交付。

Q22 终裁管线：LLM 检测标记（含畸形变体）→ 快照备份 → 正则剥离【R#】→
确定性 diff 校验（变更行只含标记，否则判误伤）→ LLM 语义校验 →
备份版 + 干净版两份交付。output_clean = missing 空 且 误伤空 且 语义全过
且 畸形空；任一不过由 check_proper_output 节点回 planner 开新环。

畸形态裁定：MALFORMED_RE 命中 → 判不过（检测层抓到即拦——畸形不是
"留在文本里不管"，而是作为独立失败类别进 malformed 列表）。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from project_agent.protocol import Role

# 【R3】/【R1-R5】/【R1-R5-compact】——正常轮次标记三形态
MARKER_RE = re.compile(r"【R\d+(-R\d+)?(-compact)?】")
# 畸形变体：【R 3】/【 R3 】/悬空【R/R3】——正常标记之外的近似残留
MALFORMED_RE = re.compile(r"【\s*R\s*\d+\s*】|【R|R\d+】")

_SEMANTIC_OK_RE = re.compile(r"semantic_ok:\s*(true|false)")

# 快照/干净版后缀目录（root 下；快照只收 .md/.txt）
BACKUP_DIRNAME = "deliverables_backup"
CLEAN_DIRNAME = "deliverables_clean"
_SNAPSHOT_SUFFIXES = frozenset({".md", ".txt"})


def _normal_spans(text: str) -> list[tuple[int, int]]:
    """正常标记的字符区间表（畸形检测的扣除基准）。"""
    return [m.span() for m in MARKER_RE.finditer(text)]


def _in_spans(pos_start: int, pos_end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos_start and pos_end <= end for start, end in spans)


def detect_markers(text: str) -> list[str]:
    """全部标记（含畸形）原文匹配列表，按出现顺序。

    畸形判定 = MALFORMED_RE 命中且不完全落在任一正常标记区间内
    （正常标记自身会被 MALFORMED_RE 的宽松分支部分命中——扣除之）。
    """
    found = [m.group(0) for m in MARKER_RE.finditer(text)]
    spans = _normal_spans(text)
    for hit in MALFORMED_RE.finditer(text):
        if not _in_spans(hit.start(), hit.end(), spans):
            found.append(hit.group(0))
    return found


def strip_markers(text: str) -> tuple[str, list[str]]:
    """(剥离后文本, 被剥标记列表)——仅 MARKER_RE 剥离；畸形留给检测层报告。"""
    markers = [m.group(0) for m in MARKER_RE.finditer(text)]
    return MARKER_RE.sub("", text), markers


def snapshot_dir(root: Path) -> Path:
    """root/deliverables_backup 快照目录：复制 root 下全部 .md/.txt 文件。

    files-only 变体（shutil.copytree 的替代）：mkdir + 逐文件 copy——
    空目录不复制、非 .md/.txt 文件不复制；backup/clean 目录自身排除
    （终检环重入时不自拷贝）。
    """
    root = Path(root)
    backup = root / BACKUP_DIRNAME
    backup.mkdir(parents=True, exist_ok=True)
    excluded = {backup, root / CLEAN_DIRNAME}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SNAPSHOT_SUFFIXES:
            continue
        if any(parent == ex for ex in excluded for parent in path.parents):
            continue
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)
    return backup


def diff_lines(before: str, after: str) -> list[tuple[str, str]]:
    """逐行 diff：[(before_line, after_line)] 仅差异行（顺序对齐 zip）。

    长度不齐按 zip 截断；调用方（marker_only_diff）对行数不等另有判。
    """
    pairs: list[tuple[str, str]] = []
    for b, a in zip(before.splitlines(), after.splitlines()):
        if b != a:
            pairs.append((b, a))
    return pairs


def _split_lines(text: str) -> list[str]:
    """行切分：空文本→零行（与剥离后空文本对齐）。"""
    return text.splitlines()


def marker_only_diff(before: str, after: str) -> bool:
    """确定性 diff 校验：每差异行剥标记后必须相等（顺序对齐）。

    - 行数不等：短侧以 "" 补齐对位（整行标记剥离后即空行）——补齐后
      仍剥不等 → False（真实内容增删，非纯标记变更）
    - 每差异行：(before_line.lstrip() == after_line.lstrip() + 标记) 或
      (before_line 剥标记后 == after_line)——两式都不满足 → False（误伤）
    """
    before_lines = _split_lines(before)
    after_lines = _split_lines(after)
    width = max(len(before_lines), len(after_lines))
    padded_before = [*before_lines, *[""] * (width - len(before_lines))]
    padded_after = [*after_lines, *[""] * (width - len(after_lines))]
    for before_line, after_line in zip(padded_before, padded_after):
        if before_line == after_line:
            continue
        stripped, _ = strip_markers(before_line)
        if stripped != after_line:
            return False
    return True


def llm_semantic_check(model: Any, before: str, after: str, *, thread_id: str) -> bool:
    """LLM 语义校验（fail-closed）：解析 semantic_ok: true/false。

    prompt 逐字终裁；role="finalizer"；解析失败/模型异常 → False。
    """
    prompt = (
        f"对比两份文档，判断剥离轮次标记是否造成语义损失。\n"
        f"剥离前：\n{before}\n"
        f"剥离后：\n{after}\n"
        "输出一行：semantic_ok: true 或 semantic_ok: false"
    )
    try:
        result = model.complete(
            [{"role": "user", "content": prompt}],
            role=Role.FINALIZER.value,
            thread_id=thread_id,
        )
        text = str(result.text)
    except Exception:
        return False  # fail-closed：模型不可用即语义失败
    match = _SEMANTIC_OK_RE.search(text)
    return bool(match and match.group(1) == "true")


def run_final_check(
    *,
    root: Path,
    deliverable_set: tuple[str, ...],
    model: Any,
    thread_id: str,
) -> dict[str, Any]:
    """完整管线（纯函数式返回 update dict）：

    1. 对账：deliverable_set 每文件 (root/文件名).exists()？缺→missing
    2. 快照：snapshot_dir(root)（全部 .md/.txt，含缺失时的已存文件）
    3. 每文件：read_text → strip_markers → marker_only_diff？False→误伤
    4. LLM 语义校验（每文件 before/after）——任一 False→语义失败
    5. 畸形检测：MALFORMED_RE 扫描原文——命中列表（检测层抓到即拦）
    6. 写干净版：root/deliverables_clean/文件名（剥离后内容；子目录 mkdir）
    """
    root = Path(root)
    missing: list[str] = []
    false_positives: list[str] = []
    semantic_failures: list[str] = []
    malformed: list[str] = []

    for name in deliverable_set:
        if not (root / name).exists():
            missing.append(name)

    backup = snapshot_dir(root)
    clean = root / CLEAN_DIRNAME
    clean.mkdir(parents=True, exist_ok=True)

    for name in deliverable_set:
        if name in missing:
            continue
        before = (root / name).read_text(encoding="utf-8")
        after, _taken = strip_markers(before)

        if not marker_only_diff(before, after):
            false_positives.append(name)

        if not llm_semantic_check(model, before, after, thread_id=thread_id):
            semantic_failures.append(name)

        # 畸形检测：MALFORMED_RE 扫描原文；落在正常标记区间内的命中扣除
        spans = _normal_spans(before)
        for hit in MALFORMED_RE.finditer(before):
            if not _in_spans(hit.start(), hit.end(), spans):
                malformed.append(name)
                break

        # 写干净版（子目录 mkdir）
        target = clean / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(after, encoding="utf-8")

    output_clean = not (
        missing or false_positives or semantic_failures or malformed
    )
    return {
        "output_clean": output_clean,
        "missing": missing,
        "false_positives": false_positives,
        "semantic_failures": semantic_failures,
        "malformed": malformed,
        "delivery_paths": {
            "backup": str(backup),
            "clean": str(clean),
        },
    }
