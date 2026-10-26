"""清欠账 Q75：旁路问答历史持久化 + 指引链接验证（用户故事 36）。"""

from __future__ import annotations

import json
import pathlib

from project_agent.ask_agent import AskBypass
from project_agent.assist_link import annotate_links, extract_links
from project_agent.model_client import ModelResult


class _EchoModel:
    """桩模型：把最后一条 user 内容回显成答案。"""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def complete(self, messages, *, role, thread_id):
        self.calls.append([dict(m) for m in messages])
        return ModelResult(text=f"答：{messages[-1]['content'][:20]}")


# ---- 旁路历史持久化（原欠账"重启即失"）----

def test_ask_bypass_memory_only_by_default() -> None:
    """既有行为：不传 history_path → 仅内存（零改动）。"""
    bypass = AskBypass(_EchoModel(), None, "t-ask")
    assert bypass.history == []
    bypass.ask("为什么用 LangGraph")
    assert len(bypass.history) == 2  # user + assistant


def test_ask_bypass_persists_history_to_disk(tmp_path: pathlib.Path) -> None:
    """v2.4：历史落盘（原子写）。"""
    path = tmp_path / "ask.history.json"
    bypass = AskBypass(_EchoModel(), None, "t-ask", history_path=path)
    bypass.ask("第一个问题")
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["role"] == "user"


def test_ask_bypass_resumes_history_after_restart(tmp_path: pathlib.Path) -> None:
    """**核心**：新建实例读到上次历史——重启不再丢失追问上下文。"""
    path = tmp_path / "ask.history.json"
    first = AskBypass(_EchoModel(), None, "t-ask", history_path=path)
    first.ask("第一问")
    first.ask("第二问")

    second = AskBypass(_EchoModel(), None, "t-ask", history_path=path)
    assert len(second.history) == 4, "重启后应接续 4 条历史"
    assert second.history[0]["role"] == "user"


def test_ask_bypass_tolerates_corrupt_history_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "ask.history.json"
    path.write_text("{broken", encoding="utf-8")
    bypass = AskBypass(_EchoModel(), None, "t-ask", history_path=path)
    assert bypass.history == []  # 不崩，空历史开场


def test_ask_bypass_tolerates_non_list_history(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "ask.history.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")
    assert AskBypass(_EchoModel(), None, "t-ask", history_path=path).history == []


def test_ask_bypass_save_is_atomic_no_tmp_left(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "ask.history.json"
    AskBypass(_EchoModel(), None, "t-ask", history_path=path).ask("q")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_ask_bypass_creates_parent_dir(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "deep" / "dir" / "ask.history.json"
    AskBypass(_EchoModel(), None, "t-ask", history_path=path).ask("q")
    assert path.is_file()


def test_ask_bypass_save_failure_does_not_break_answer(tmp_path: pathlib.Path) -> None:
    """落盘失败不砸掉本次问答（下轮再试）。"""

    class _Boom:
        def mkdir(self, *a, **k):
            raise OSError("磁盘不可写")

    bypass = AskBypass(_EchoModel(), None, "t-ask", history_path=_Boom())
    assert bypass.ask("问题").startswith("答：")


# ---- 指引链接验证（用户故事 36）----

def test_extract_links_finds_urls_and_strips_trailing_punct() -> None:
    text = "参见 https://example.com/a。与 https://example.com/b?x=1，以及 https://example.com/a"
    assert extract_links(text) == ("https://example.com/a", "https://example.com/b?x=1")


def test_annotate_links_no_fetch_leaves_text_untouched() -> None:
    """无验证能力时不乱标（`fetch=None` 且无 known）。"""
    text = "见 https://example.com/x"
    assert annotate_links(text) == text


def test_annotate_links_marks_dead_link() -> None:
    text = "见 https://dead.example/x 与 https://ok.example/y"
    fetch = lambda url: None if "dead" in url else "content"  # noqa: E731
    out = annotate_links(text, fetch=fetch)
    assert "https://dead.example/x（链接未验证）" in out
    assert "https://ok.example/y" in out
    assert "（链接未验证）" not in out.replace("https://dead.example/x（链接未验证）", "")


def test_annotate_links_marks_on_exception() -> None:
    def boom(url):
        raise OSError("网络不通")

    out = annotate_links("https://x.example/a", fetch=boom)
    assert "（链接未验证）" in out


def test_annotate_links_uses_preset_verified_set() -> None:
    """已知可达集合 → 不抓取、不标注。"""
    out = annotate_links(
        "https://ok.example/a", verified={"https://ok.example/a"}, fetch=None
    )
    assert "（链接未验证）" not in out


def test_annotate_links_empty_content_counts_as_dead() -> None:
    out = annotate_links("https://x.example/a", fetch=lambda url: "")
    assert "（链接未验证）" in out


# ---- current_scope 写者（原欠账）----

def test_actor_declares_current_scope(tmp_path: pathlib.Path) -> None:
    """actor 通过"作用域："指令桥声明 current_scope（原欠账）。"""
    from project_agent.model_client import ModelResult, ToolAwareResult
    from project_agent.nodes import make_actor_node

    class _ScopeModel:
        def complete(self, messages, *, role, thread_id):
            return ModelResult(text="作用域：docs\n本轮整理了文档结构。")

        def complete_with_tools(self, messages, tools, *, role, thread_id):
            return ToolAwareResult(text="作用域：docs\n本轮整理了文档结构。")

    state = {
        "task_brief": "写文档",
        "build_way": "way3",
        "workspace_root": str(tmp_path),
        "actor_messages": [],
        "todos": [],
    }
    updates = make_actor_node(_ScopeModel())(state, None)
    assert updates.get("current_scope") == "docs", f"实际 {updates.get('current_scope')!r}"
