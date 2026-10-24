"""假 shell：记录调用 + 预置输出/拒绝（工具边界测试替身）。"""

from __future__ import annotations


class RecordingShell:
    def __init__(
        self, outputs: dict[str, str] | None = None, denied: tuple[str, ...] = ()
    ) -> None:
        self.calls: list[str] = []
        self._outputs = dict(outputs or {})
        self._denied = set(denied)

    def run(self, command: str) -> str:
        self.calls.append(command)
        if command in self._denied:
            raise PermissionError(f"deny: {command}")
        return self._outputs.get(command, "")
