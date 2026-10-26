"""AskAgent 双通道（10 票）：REPL 旁路直答 + 图内新手指引注入。

隔离红线（ADR-0002）在两条通道同样生效：
- 旁路只读磁盘共享文档切片（SharedDocs），**不读主线对话历史**；问答历史
  留在 AskBypass 自己的 history（独立 thread），绝不写主图 state。
- 图内指引材料包同样只含 round_summary + Notepad 条目 + 文档切片，单发
  模型调用无历史累积；返回文本由 actor 节点只放 turn_end_payload.round_output，
  不写任何主线角色私有 key。

工具面：ASK_TOOLSET = 权限矩阵只读 10 件（构造期预注册，无写权/Shell）。
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

from project_agent.tools.registry import ToolRegistry

# 验收 5：AskAgent 工具面 = 矩阵只读集（10 件；无 FileWrite/FileEdit/
# Shell/TodoWrite/DocScaffold）
ASK_TOOLSET: tuple[str, ...] = ToolRegistry().tools_for("ask_agent")

_ASK_ROLE = "ask_agent"


def build_ask_context(
    shared_docs: Any, question: str
) -> list[dict[str, str]]:
    """旁路上下文：直读磁盘项目文档切片（非主线历史）。

    返回单条 user 消息：项目文档（逐条【R#】切片拼接）+ 问题；
    shared_docs=None → 裸问题（无文档区可读）。
    """
    if shared_docs is None:
        return [{"role": "user", "content": question}]
    doc_slice = "\n".join(
        content for _round_no, content in shared_docs.read_rounds()
    )
    return [
        {
            "role": "user",
            "content": f"项目文档：\n{doc_slice}\n\n问题：{question}",
        }
    ]


def ask_answer(
    model: Any,
    shared_docs: Any,
    question: str,
    *,
    history: Sequence[Mapping[str, Any]],
    thread_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    """旁路单次问答：history + 新上下文 → ask_agent → (文本, 累积历史)。

    返回的新历史 = 入参 history（原样前缀）+ 本轮 context + assistant 文本；
    入参 history 不被修改（下一次追问传入上次返回值即上下文保持）。
    """
    context = build_ask_context(shared_docs, question)
    messages = [dict(message) for message in history] + context
    result = model.complete(messages, role=_ASK_ROLE, thread_id=thread_id)
    text = str(result.text)
    return text, [*messages, {"role": "assistant", "content": text}]


class AskBypass:
    """REPL 旁路会话：独立 thread 的问答历史自累积（不触碰主图 state）。

    **持久化（v2.4 落地）**：历史落 `history_path`（JSON，旁路 thread 专属）。
    `history_path=None` → 仅内存（既有行为，测试零改动）。重启即失的旧欠账
    由此清掉：同一项目再次 `/ask-for-help` 时接续上次的追问上下文。
    """

    def __init__(
        self,
        model: Any,
        shared_docs: Any,
        thread_id: str,
        *,
        history_path: Any = None,
    ) -> None:
        self._model = model
        self._shared_docs = shared_docs
        self._thread_id = thread_id
        self._history_path = history_path
        self.history: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        """读盘上历史；文件缺失/损坏/路径异常 → 空历史（不阻断开场）。"""
        if self._history_path is None:
            return []
        import json

        try:
            raw = self._history_path.read_text(encoding="utf-8")
        except (OSError, AttributeError):
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _save(self) -> None:
        """原子写历史（临时文件 + 替换，防写到半截）。"""
        if self._history_path is None:
            return
        import json
        import os

        target = self._history_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(json.dumps(self.history, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, target)
        except (OSError, AttributeError):
            pass  # 落盘失败不砸掉本次问答（下轮再试）

    def ask(self, question: str) -> str:
        text, self.history = ask_answer(
            self._model,
            self._shared_docs,
            question,
            history=self.history,
            thread_id=self._thread_id,
        )
        self._save()
        return text


def guidance_material_pack(
    *,
    round_summary: str,
    notes: Iterable[tuple[int, str]],
    doc_slice: str,
) -> str:
    """指引材料包（纯函数）：为什么这么做 + 下一步 + 技术栈文档 + Notepad 行。"""
    head = (
        f"为什么这么做：本轮 {round_summary}\n"
        "下一步：推进 todo 板\n"
        f"技术栈文档：\n{doc_slice}\n"
    )
    note_lines = "".join(f"【R{no}】- {note}\n" for no, note in notes)
    return head + note_lines


def build_guidance(
    model: Any,
    *,
    round_summary: str,
    notes: Iterable[tuple[int, str]],
    doc_slice: str,
    thread_id: str,
) -> str:
    """图内新手指引：材料包单发模型调用（无历史累积），返回指引文本。

    绝不写任何主线私有 key——调用方（actor 节点）只把返回值放
    turn_end_payload.round_output 尾部。
    """
    material = guidance_material_pack(
        round_summary=round_summary, notes=notes, doc_slice=doc_slice
    )
    result = model.complete(
        [{"role": "user", "content": material}],
        role=_ASK_ROLE,
        thread_id=thread_id,
    )
    return str(result.text)


def verify_link(url: str, fetch: Callable[[str], str | None]) -> bool:
    """链接抓取验证：fetch 返回非 None 且非空 → True；None/异常 → False（死链拒）。"""
    try:
        content = fetch(url)
    except Exception:
        return False
    return content is not None and content != ""
