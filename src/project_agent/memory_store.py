"""跨线程长期记忆 Store（12 票，轻实现终裁）。

final_report 入 Store：finalizer 节点写入，新会话 ask_tasks 时可检索注入
（模拟跨 thread 检索）。langgraph Store 正式接入留接线票——本模块与其
API 形态兼容（put/get 按 key），接线票替换实现即可。

key 简化终裁 = task_brief 原文（f"final_report:{task_brief}"）——
不做哈希，模拟新会话测试直接 get 断言。
"""

from __future__ import annotations

from typing import Any


class InMemoryStore:
    """dict 按 key 存取：put(key, value) / get(key)（无→None）。"""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str) -> Any:
        return self._data.get(key)
