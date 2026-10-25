"""07 票：交付物集定义表（对账表驱动）——各构建方式的交付物清单。

票 07 终裁 A：DELIVERABLE_SETS 是验收 4 对账表驱动对象；终检票（12）消费此表。
deliverables_for(way) 未知 way → ()。
"""

from __future__ import annotations

import pytest

from project_agent.deliverables import DELIVERABLE_SETS, deliverables_for


@pytest.mark.parametrize(
    ("way", "expected"),
    [
        ("way1", ()),  # 对话无交付物
        ("way2", ("IDEA.md",)),
        ("way3", ("README.md", "TODO.md", "目录树.txt")),
        (
            "way4",
            (
                "README.md",
                "TODO.md",
                "目录树.txt",
                "docs/需求规格.md",
                "docs/技术选型.md",
                "docs/目录结构.md",
            ),
        ),
    ],
    ids=["way1-empty", "way2-idea", "way3-simple-docs", "way4-full-docs"],
)
def test_deliverable_sets_table(way: str, expected: tuple[str, ...]):
    assert DELIVERABLE_SETS[way] == expected
    assert deliverables_for(way) == expected


@pytest.mark.parametrize(
    "way",
    ["way5", "way9", "", "unknown", "WAY1", "way0", None],
    ids=["way5", "way9", "empty", "unknown", "upper", "zero", "none"],
)
def test_unknown_way_returns_empty_tuple(way):
    """未知 way → ()（空 tuple 而非 None/异常：对账表驱动的防御语义）。"""
    assert deliverables_for(way) == ()


def test_deliverable_sets_covers_exactly_four_ways():
    """表只含 way1–way4 四键（受控词汇）。"""
    assert set(DELIVERABLE_SETS) == {"way1", "way2", "way3", "way4"}


def test_way4_set_is_superset_of_way3():
    """完整文档 ⊃ 简化文档：文档集嵌套（对账不漏项的结构依据）。"""
    assert set(DELIVERABLE_SETS["way3"]) < set(DELIVERABLE_SETS["way4"])
