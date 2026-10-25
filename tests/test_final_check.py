"""12 票切片 1：final_check 纯函数套件 + run_final_check 终检管线。

验收映射：②畸形变体（detect_markers/run 注入）；③确定性 diff
（marker_only_diff 表驱动：纯标记变更过/混入内容变更不过）；①双份交付
（run 干净路径 backup+clean）；⑥对账表驱动（deliverable_set 缺文件→missing）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from project_agent.final_check import (
    detect_markers,
    diff_lines,
    llm_semantic_check,
    marker_only_diff,
    run_final_check,
    snapshot_dir,
    strip_markers,
)
from tests.doubles.fake_model import ScriptedModel

WAY3_FILES = ("README.md", "TODO.md", "目录树.txt")


def _seed_way3(root: Path) -> None:
    """预写带【R#】的 3 份交付物（way3 文档集）。"""
    (root / "README.md").write_text(
        "【R1】# 记账 CLI\n【R2】轻量工具\n", encoding="utf-8"
    )
    (root / "TODO.md").write_text("【R3】- 勾选清单\n", encoding="utf-8")
    (root / "目录树.txt").write_text("【R4】root\n", encoding="utf-8")


# —— MARKER_RE / strip_markers：正常标记三形态，畸形留给检测层 ——


@pytest.mark.parametrize(
    "marker", ["【R3】", "【R12】", "【R1-R5】", "【R1-R5-compact】"]
)
def test_strip_markers_removes_normal_variants(marker):
    stripped, taken = strip_markers(f"前{marker}后")
    assert taken == [marker]
    assert stripped == "前后"


def test_strip_markers_removes_only_normal_leaves_malformed():
    """仅 MARKER_RE 剥离；畸形变体留给检测层报告。"""
    text = "【R3】标题\n【R 3】畸形行"
    stripped, taken = strip_markers(text)
    assert taken == ["【R3】"]
    assert "【R3】" not in stripped
    assert "【R 3】" in stripped


# —— detect_markers：全部标记（含畸形）原文匹配列表 ——


def test_detect_markers_lists_normal_and_malformed_in_order():
    text = "【R1】开头\n正文【R 2】中缀\n结尾 R3】悬空"
    markers = detect_markers(text)
    assert markers == ["【R1】", "【R 2】", "R3】"]


def test_detect_markers_pure_normal_text_has_no_malformed_noise():
    """正常标记（含区间压缩形态）不产畸形噪音。"""
    text = "【R1】a\n【R2-R6-compact】b\n【R7-R9】c"
    assert detect_markers(text) == ["【R1】", "【R2-R6-compact】", "【R7-R9】"]


def test_detect_markers_empty_text():
    assert detect_markers("") == []


# —— diff_lines：仅差异行（顺序对齐） ——


def test_diff_lines_returns_only_differing_pairs_in_order():
    assert diff_lines("a\nb\nc", "a\nX\nc") == [("b", "X")]
    assert diff_lines("a\nb", "a\nb") == []


# —— marker_only_diff：确定性 diff 校验（验收 ③表驱动） ——


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # 纯标记变更 → 过
        ("【R3】标题\n正文行", "标题\n正文行", True),
        ("前【R1-R5-compact】后", "前后", True),
        ("【R3】", "", True),
        ("x【R3】", "x", True),
        ("完全一致\n无标记", "完全一致\n无标记", True),
        # 混入内容变更 → 不过（误伤）
        ("【R3】内容A", "内容B", False),
        ("【R3】内容A", "内容A 追加", False),
        ("【R3】第一行\n第二行", "第一行", False),  # 删除行
        ("【R3】第一行", "第一行\n新增行", False),  # 新增行
    ],
    ids=[
        "marker-only-pass",
        "inline-range-pass",
        "marker-only-line-pass",
        "trailing-marker-pass",
        "identical-pass",
        "content-changed-fail",
        "content-appended-fail",
        "line-deleted-fail",
        "line-added-fail",
    ],
)
def test_marker_only_diff_table_driven(before, after, expected):
    assert marker_only_diff(before, after) is expected


# —— snapshot_dir：root/deliverables_backup 快照（全部 .md/.txt） ——


def test_snapshot_dir_copies_md_txt_files_only(tmp_path):
    (tmp_path / "README.md").write_text("r", encoding="utf-8")
    (tmp_path / "BUILD_LOG.md").write_text("【R1】x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("n", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "需求.md").write_text("d", encoding="utf-8")

    backup = snapshot_dir(tmp_path)

    assert backup == tmp_path / "deliverables_backup"
    assert (backup / "README.md").read_text(encoding="utf-8") == "r"
    assert (backup / "BUILD_LOG.md").exists()
    assert (backup / "notes.txt").exists()
    assert (backup / "sub" / "需求.md").exists()
    assert not (backup / "data.json").exists()


def test_snapshot_dir_reentry_overwrites_without_self_copy(tmp_path):
    """终检环重入：快照覆写更新，backup/clean 目录自身不参与拷贝。"""
    snapshot_dir(tmp_path)
    (tmp_path / "a.md").write_text("v2", encoding="utf-8")

    snapshot_dir(tmp_path)

    backup = tmp_path / "deliverables_backup"
    assert (backup / "a.md").read_text(encoding="utf-8") == "v2"
    assert not (backup / "deliverables_backup").exists()
    assert not (backup / "deliverables_clean").exists()


# —— llm_semantic_check：fail-closed 解析 ——


def test_llm_semantic_check_true_false_and_fail_closed():
    ok = ScriptedModel(["semantic_ok: true"])
    no = ScriptedModel(["semantic_ok: false"])
    junk = ScriptedModel(["我认为语义没有损失"])
    assert llm_semantic_check(ok, "前【R1】文", "前文", thread_id="t") is True
    assert llm_semantic_check(no, "前【R1】文", "前文", thread_id="t") is False
    assert llm_semantic_check(junk, "前【R1】文", "前文", thread_id="t") is False


def test_llm_semantic_check_model_error_fail_closed():
    class Boom:
        def complete(self, messages, *, role, thread_id):
            raise RuntimeError("模型不可用")

    assert llm_semantic_check(Boom(), "a", "a", thread_id="t") is False


def test_llm_semantic_check_prompt_role_and_thread():
    model = ScriptedModel(["semantic_ok: true"])
    llm_semantic_check(model, "前文", "后文", thread_id="th-1")
    call = model.calls[0]
    assert call["role"] == "finalizer"
    assert call["thread_id"] == "th-1"
    content = call["messages"][0]["content"]
    assert "剥离前：" in content
    assert "前文" in content
    assert "剥离后：" in content
    assert "后文" in content


# —— run_final_check：完整管线 ——


def test_run_final_check_clean_double_delivery(tmp_path):
    """干净路径：output_clean 真 + 备份版（保留标记）+ 干净版（零残留）。"""
    _seed_way3(tmp_path)
    model = ScriptedModel(["semantic_ok: true"] * 3)

    result = run_final_check(
        root=tmp_path, deliverable_set=WAY3_FILES, model=model, thread_id="t1"
    )

    assert result["output_clean"] is True
    assert result["missing"] == []
    assert result["false_positives"] == []
    assert result["semantic_failures"] == []
    assert result["malformed"] == []
    backup = Path(result["delivery_paths"]["backup"])
    clean = Path(result["delivery_paths"]["clean"])
    assert backup == tmp_path / "deliverables_backup"
    assert clean == tmp_path / "deliverables_clean"
    # 备份版保留标记；原文不动（磁盘为事实来源）
    assert "【R1】" in (backup / "README.md").read_text(encoding="utf-8")
    assert "【R1】" in (tmp_path / "README.md").read_text(encoding="utf-8")
    # 干净版：剥离后内容，零【R#】残留
    clean_readme = (clean / "README.md").read_text(encoding="utf-8")
    assert clean_readme == "# 记账 CLI\n轻量工具\n"
    assert "【R" not in clean_readme
    assert "【R" not in (clean / "TODO.md").read_text(encoding="utf-8")
    assert "【R" not in (clean / "目录树.txt").read_text(encoding="utf-8")
    # 每文件一次语义校验调用
    assert len(model.calls) == 3


def test_run_final_check_missing_file_reported(tmp_path):
    (tmp_path / "README.md").write_text("【R1】x\n", encoding="utf-8")
    model = ScriptedModel(["semantic_ok: true"])

    result = run_final_check(
        root=tmp_path, deliverable_set=WAY3_FILES, model=model, thread_id="t"
    )

    assert result["missing"] == ["TODO.md", "目录树.txt"]
    assert result["output_clean"] is False
    assert len(model.calls) == 1  # 缺文件不做语义校验


def test_run_final_check_malformed_variant_blocks(tmp_path):
    """验收 ②：畸形变体注入 → 检测层抓到即拦（判不过）。"""
    _seed_way3(tmp_path)
    (tmp_path / "TODO.md").write_text("【R 3】- 勾选清单\n", encoding="utf-8")
    model = ScriptedModel(["semantic_ok: true"] * 3)

    result = run_final_check(
        root=tmp_path, deliverable_set=WAY3_FILES, model=model, thread_id="t"
    )

    assert result["malformed"] == ["TODO.md"]
    assert result["output_clean"] is False
    # 畸形不阻塞其余工序：备份与干净版照产
    assert (Path(result["delivery_paths"]["backup"]) / "TODO.md").exists()
    assert (Path(result["delivery_paths"]["clean"]) / "TODO.md").exists()


def test_run_final_check_semantic_failure_reported(tmp_path):
    _seed_way3(tmp_path)
    model = ScriptedModel(
        ["semantic_ok: true", "semantic_ok: false", "semantic_ok: true"]
    )

    result = run_final_check(
        root=tmp_path, deliverable_set=WAY3_FILES, model=model, thread_id="t"
    )

    assert result["semantic_failures"] == ["TODO.md"]
    assert result["output_clean"] is False


def test_run_final_check_false_positive_plumbing(tmp_path, monkeypatch):
    """误伤安全网接线：确定性 diff 判误伤 → false_positives 列表 + 不过。"""
    import project_agent.final_check as fc

    _seed_way3(tmp_path)
    monkeypatch.setattr(fc, "marker_only_diff", lambda before, after: False)
    model = ScriptedModel(["semantic_ok: true"] * 3)

    result = fc.run_final_check(
        root=tmp_path, deliverable_set=WAY3_FILES, model=model, thread_id="t"
    )

    assert result["false_positives"] == ["README.md", "TODO.md", "目录树.txt"]
    assert result["output_clean"] is False


def test_run_final_check_rerun_is_stable(tmp_path):
    """终检环重入：原文未变时复检结论一致（幂等）。"""
    _seed_way3(tmp_path)
    model = ScriptedModel(["semantic_ok: true"] * 6)
    args = {"root": tmp_path, "deliverable_set": WAY3_FILES, "thread_id": "t"}

    first = run_final_check(model=model, **args)
    second = run_final_check(model=model, **args)

    assert first["output_clean"] is True
    assert second["output_clean"] is True
    assert first["delivery_paths"] == second["delivery_paths"]
