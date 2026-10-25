"""交付物集定义表（07 票终裁 A）：各构建方式的交付物清单。

对账表驱动对象：验收 4（轻方式不生成 way3/4 文档集）与终检票（12）
消费此表。磁盘为事实来源（ADR-0004），本表只是"应有何物"的清单——
实际生长由 grilling 身体逐轮驱动（文档长出来而非倒出来）。
"""

from __future__ import annotations

DELIVERABLE_SETS: dict[str, tuple[str, ...]] = {
    "way1": (),  # 对话无交付物
    "way2": ("IDEA.md",),
    "way3": ("README.md", "TODO.md", "目录树.txt"),
    "way4": (
        "README.md",
        "TODO.md",
        "目录树.txt",
        "docs/需求规格.md",
        "docs/技术选型.md",
        "docs/目录结构.md",
    ),
}


def deliverables_for(build_way: str) -> tuple[str, ...]:
    """查询某构建方式的交付物集；未知 way → （）（防御：不报错不猜）。"""
    return DELIVERABLE_SETS.get(build_way, ())
