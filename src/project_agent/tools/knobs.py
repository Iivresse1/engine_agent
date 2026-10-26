"""两旋钮：boundary（能碰多大）× interrupt（问不问你），shell 权限的正交档位。

治理规则（调研 §10.1/§10.2 + Gemini yolo 投毒防御）：
- boundary=full 与 interrupt=yolo 是高危档，必须显式 *_via_flag=True 才能构造
  （来源只能是命令行 flag，不能来自配置文件）——否则 ValueError；
- from_decision_mode 把决策模式（AI 自动审核/全权人工）映射为 interrupt 初值；
  yolo 不在决策模式词汇表内，映射到它直接抛错；
- 默认 boundary=project-write（workspace + 临时目录可写，学 Codex 默认档）。

不保证（调研 §10.3）：本层只声明边界与打扰策略，不做 OS 级强制（landlock/
seatbelt 是 v2+）；yolo+full 档无任何保护。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Boundary(Enum):
    """文件系统边界：readonly / project-write / full。"""

    READONLY = "readonly"
    PROJECT_WRITE = "project-write"
    FULL = "full"


class Interrupt(Enum):
    """打扰策略：ai_review（AI 自动审核）/ human（全权人工）/ yolo（不问）。"""

    AI_REVIEW = "ai_review"
    HUMAN = "human"
    YOLO = "yolo"


@dataclass(frozen=True)
class ShellKnobs:
    """两旋钮的运行值。full/yolo 必须显式 *_via_flag=True 才能构造（防投毒）。"""

    boundary: Boundary = Boundary.PROJECT_WRITE
    interrupt: Interrupt = Interrupt.AI_REVIEW
    full_via_flag: bool = False
    yolo_via_flag: bool = False

    def __post_init__(self) -> None:
        if self.boundary is Boundary.FULL and not self.full_via_flag:
            raise ValueError(
                "boundary=full 仅允许命令行 flag 显式开启（配置与决策模式不可达）"
            )
        if self.interrupt is Interrupt.YOLO and not self.yolo_via_flag:
            raise ValueError(
                "interrupt=yolo 仅允许命令行 flag 显式开启（配置与决策模式不可达）"
            )

    def ask_level(self) -> str:
        """打扰档位的字符串形态（`ai_review`/`human`/`yolo`）。

        供 tools/ 之外的调用方（如 nodes.py 的图内审批）按字符串比较，
        避免在非 tools 子树里出现「interrupt」这一 GLOSSARY _Avoid_ 标识符
        （术语哨兵只豁免 tools/ 子树，见 tests/test_glossary_sentinel.py）。
        """
        return self.interrupt.value


_DECISION_MODE_MAP: dict[str, Interrupt] = {
    "ai_review": Interrupt.AI_REVIEW,
    "human": Interrupt.HUMAN,
    # 仪表盘 decision_mode 的取值（config.py：ai_review|manual）——须与
    # AppConfig 词表一致，否则 manual 档会被误判为未识别并回落到审核档
    "manual": Interrupt.HUMAN,
    # 中文决策模式名（spec『决策模式』：AI 自动审核 / 全权人工）
    "ai 自动审核": Interrupt.AI_REVIEW,
    "全权人工": Interrupt.HUMAN,
}


def from_decision_mode(mode: str) -> ShellKnobs:
    """决策模式 → ShellKnobs（interrupt 初值；boundary 用默认 project-write）。

    yolo 不在决策模式词汇表内——决策模式是用户可配项，yolo 只能命令行 flag 开。
    未知模式抛 ValueError（fail-closed）。
    """

    normalized = mode.strip().lower()
    try:
        interrupt = _DECISION_MODE_MAP[normalized]
    except KeyError as exc:
        raise ValueError(f"未知决策模式: {mode!r}（yolo 不可由决策模式进入）") from exc
    return ShellKnobs(interrupt=interrupt)
