"""脚本化终端 IO：预置输入行序列 + 捕获全部输出（REPL 宿主的测试替身）。"""

from __future__ import annotations


class ScriptedIO:
    def __init__(self, lines: list[str] | None = None) -> None:
        self._lines = list(lines or [])
        self.outputs: list[str] = []

    def read_line(self) -> str | None:
        if not self._lines:
            return None
        return self._lines.pop(0)

    def write_line(self, text: str) -> None:
        self.outputs.append(text)
