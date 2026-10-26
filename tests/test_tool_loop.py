"""工具执行回路（17 票）——六件文件工具本体 + 调用环 + 权限构造期强制。"""

from __future__ import annotations

import pathlib

import pytest

from project_agent.tools.file_tools import (
    EXECUTORS,
    ToolError,
    ToolResult,
    doc_scaffold,
    execute,
    file_edit,
    file_read,
    file_write,
    glob_files,
    grep_files,
)
from project_agent.tools.registry import ASK_AGENT, BUILDER
from project_agent.tools.tool_loop import (
    MAX_TOOL_ITERATIONS,
    TOOL_SCHEMAS,
    ToolLoop,
    tool_definitions,
)


@pytest.fixture()
def root(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path


# ---- 路径安全（三重检查）----

@pytest.mark.parametrize(
    "bad",
    ["/etc/passwd", "C:/Windows/win.ini", "../outside.txt", "a/../../escape.txt", "", "   "],
)
def test_all_file_tools_reject_unsafe_paths(root: pathlib.Path, bad: str) -> None:
    with pytest.raises(ToolError):
        file_read(root, bad)
    with pytest.raises(ToolError):
        file_write(root, bad, "x")


def test_path_outside_workspace_rejected(root: pathlib.Path) -> None:
    """即使绕开字符检查，resolve 后越界也必须拒。"""
    with pytest.raises(ToolError):
        file_read(root, "../" + pathlib.Path(root).name + "_sibling.txt")


# ---- FileRead ----

def test_file_read_returns_numbered_lines(root: pathlib.Path) -> None:
    (root / "a.md").write_text("第一行\n第二行\n第三行\n", encoding="utf-8")
    out = file_read(root, "a.md")
    assert "第 1-3 行" in out
    assert "1\t第一行" in out
    assert "3\t第三行" in out


def test_file_read_forward_slash_and_backslash_both_work(root: pathlib.Path) -> None:
    (root / "sub").mkdir()
    (root / "sub" / "b.md").write_text("内容\n", encoding="utf-8")
    assert "内容" in file_read(root, "sub/b.md")
    assert "内容" in file_read(root, "sub\\b.md")


def test_file_read_offset_limit(root: pathlib.Path) -> None:
    (root / "a.md").write_text("\n".join(f"行{i}" for i in range(1, 11)), encoding="utf-8")
    out = file_read(root, "a.md", offset=3, limit=2)
    assert "第 3-4 行" in out
    assert "行3" in out and "行4" in out and "行5" not in out


def test_file_read_bom_stripped(root: pathlib.Path) -> None:
    (root / "bom.md").write_bytes("\ufeff带BOM的内容\n".encode())
    out = file_read(root, "bom.md")
    assert "带BOM的内容" in out
    assert "\ufeff" not in out


def test_file_read_missing_file_raises(root: pathlib.Path) -> None:
    with pytest.raises(ToolError, match="不存在"):
        file_read(root, "nope.md")


def test_file_read_directory_raises(root: pathlib.Path) -> None:
    (root / "dir").mkdir()
    with pytest.raises(ToolError, match="是目录"):
        file_read(root, "dir")


def test_file_read_non_utf8_raises(root: pathlib.Path) -> None:
    (root / "bin.dat").write_bytes(b"\xff\xfe\x00\x00bad")
    with pytest.raises(ToolError, match="非 UTF-8"):
        file_read(root, "bin.dat")


# ---- Glob ----

def test_glob_finds_files(root: pathlib.Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x", encoding="utf-8")
    (root / "src" / "b.py").write_text("x", encoding="utf-8")
    (root / "readme.md").write_text("x", encoding="utf-8")
    out = glob_files(root, "src/*.py")
    assert "src/a.py" in out and "src/b.py" in out
    assert "readme.md" not in out


def test_glob_no_match(root: pathlib.Path) -> None:
    assert "无匹配" in glob_files(root, "**/*.nope")


def test_glob_rejects_parent_reference(root: pathlib.Path) -> None:
    with pytest.raises(ToolError):
        glob_files(root, "../*")


# ---- Grep ----

def test_grep_finds_pattern_with_line_numbers(root: pathlib.Path) -> None:
    (root / "a.py").write_text("alpha\nbeta 目标\ngamma\n", encoding="utf-8")
    out = grep_files(root, "目标")
    assert "a.py:2:" in out
    assert "beta 目标" in out


def test_grep_ignore_case(root: pathlib.Path) -> None:
    (root / "a.md").write_text("HELLO world\n", encoding="utf-8")
    assert "无匹配" in grep_files(root, "hello")
    assert "HELLO" in grep_files(root, "hello", ignore_case=True)


def test_grep_invalid_regex_raises(root: pathlib.Path) -> None:
    with pytest.raises(ToolError, match="正则非法"):
        grep_files(root, "[unclosed")


def test_grep_limit_enforced(root: pathlib.Path) -> None:
    (root / "big.md").write_text("\n".join("hit" for _ in range(120)), encoding="utf-8")
    out = grep_files(root, "hit")
    assert "已达上限 50 条" in out


# ---- FileWrite ----

def test_file_write_creates_parent_dirs(root: pathlib.Path) -> None:
    message = file_write(root, "deep/nested/x.md", "内容\n")
    assert (root / "deep" / "nested" / "x.md").read_text(encoding="utf-8") == "内容\n"
    assert "已写入" in message


def test_file_write_is_utf8_lf_no_bom(root: pathlib.Path) -> None:
    file_write(root, "a.md", "行1\n行2")
    raw = (root / "a.md").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw


def test_file_write_overwrites(root: pathlib.Path) -> None:
    file_write(root, "a.md", "旧")
    file_write(root, "a.md", "新")
    assert (root / "a.md").read_text(encoding="utf-8") == "新"


# ---- FileEdit ----

def test_file_edit_replaces_unique_match(root: pathlib.Path) -> None:
    (root / "a.md").write_text("开头\n旧标题\n结尾\n", encoding="utf-8")
    message = file_edit(root, "a.md", "旧标题", "新标题")
    assert (root / "a.md").read_text(encoding="utf-8") == "开头\n新标题\n结尾\n"
    assert "替换 1 处" in message


def test_file_edit_rejects_multiple_matches(root: pathlib.Path) -> None:
    """不唯一 → 报错不猜（防误改多处）。"""
    (root / "a.md").write_text("dup\ndup\n", encoding="utf-8")
    with pytest.raises(ToolError, match="必须唯一"):
        file_edit(root, "a.md", "dup", "x")


def test_file_edit_rejects_no_match(root: pathlib.Path) -> None:
    (root / "a.md").write_text("abc\n", encoding="utf-8")
    with pytest.raises(ToolError, match="未找到"):
        file_edit(root, "a.md", "zzz", "y")


def test_file_edit_missing_file_raises(root: pathlib.Path) -> None:
    with pytest.raises(ToolError, match="不存在"):
        file_edit(root, "nope.md", "a", "b")


# ---- DocScaffold ----

@pytest.mark.parametrize("way,expected", [("way2", 1), ("way3", 3), ("way4", 6)])
def test_doc_scaffold_creates_expected_count(root: pathlib.Path, way: str, expected: int) -> None:
    message = doc_scaffold(root, way)
    assert len(list(root.rglob("*"))) >= expected
    assert "已创建" in message


def test_doc_scaffold_skips_existing_without_overwrite(root: pathlib.Path) -> None:
    """已存在的交付物不覆盖（防抹掉用户/actor 已写内容）。"""
    (root / "README.md").write_text("用户自己写的\n", encoding="utf-8")
    message = doc_scaffold(root, "way3")
    assert (root / "README.md").read_text(encoding="utf-8") == "用户自己写的\n"
    assert "已存在跳过" in message
    assert "README.md" in message


def test_doc_scaffold_way1_is_noop(root: pathlib.Path) -> None:
    assert "无交付物骨架" in doc_scaffold(root, "way1")


def test_doc_scaffold_custom_subdir(root: pathlib.Path) -> None:
    doc_scaffold(root, "way2", path="sub")
    assert (root / "sub" / "IDEA.md").is_file()


# ---- execute 分派 ----

def test_execute_dispatches_and_reports_ok(root: pathlib.Path) -> None:
    result = execute(root, "FileWrite", {"path": "a.md", "content": "x"})
    assert isinstance(result, ToolResult) and result.ok
    assert "已写入" in result.content


def test_execute_unknown_tool_not_ok(root: pathlib.Path) -> None:
    result = execute(root, "NoSuchTool", {})
    assert result.ok is False
    assert "不在可执行集合内" in result.content


def test_execute_bad_arguments_not_ok(root: pathlib.Path) -> None:
    """参数不符 → ToolResult(ok=False)，不抛（回灌给模型自行改道）。"""
    result = execute(root, "FileWrite", {"path": "a.md"})  # 缺 content
    assert result.ok is False
    assert "参数不符" in result.content


def test_executor_table_matches_schemas() -> None:
    """可执行集合与 schema 表必须一致（多一件少一件都是契约漂移）。"""
    assert set(EXECUTORS) | {"NotepadAdd", "Shell"} == set(TOOL_SCHEMAS)


# ---- tool_definitions（构造期面裁剪）----

def test_builder_sees_full_tool_surface() -> None:
    names = {d["function"]["name"] for d in tool_definitions(BUILDER)}
    assert {"FileRead", "FileWrite", "FileEdit", "DocScaffold", "Shell", "Glob", "Grep"} <= names


def test_ask_agent_never_sees_write_tools() -> None:
    """权限在构造期：面外工具根本不出现在 schema 里（模型无从调用）。"""
    names = {d["function"]["name"] for d in tool_definitions(ASK_AGENT)}
    assert "FileWrite" not in names
    assert "FileEdit" not in names
    assert "Shell" not in names
    assert {"FileRead", "Glob", "Grep"} <= names


def test_tool_definitions_match_openai_shape() -> None:
    for definition in tool_definitions(BUILDER):
        assert definition["type"] == "function"
        function = definition["function"]
        assert isinstance(function["name"], str) and function["name"]
        assert function["description"]
        assert function["parameters"]["type"] == "object"


# ---- ToolLoop ----

class _FakeReply:
    def __init__(self, text: str = "", tool_calls: list[dict] | None = None) -> None:
        self.text = text
        self.tool_calls = tool_calls or []


def test_tool_loop_single_call_then_final_text(root: pathlib.Path) -> None:
    """一次工具调用 → 回灌 → 模型给终稿，环正常收敛。"""
    replies = [
        _FakeReply(tool_calls=[{"id": "c1", "name": "FileWrite", "args": {"path": "a.md", "content": "hi"}}]),
        _FakeReply(text="写好了"),
    ]
    sent: list[list] = []

    def complete(messages, definitions):
        sent.append(list(messages))
        return replies.pop(0)

    from functools import partial

    loop = ToolLoop(role=BUILDER, runner=partial(execute, root))
    outcome = loop.run(complete, [{"role": "user", "content": "写个文件"}])
    assert outcome.text == "写好了"
    assert len(outcome.invocations) == 1
    assert outcome.invocations[0].ok
    assert (root / "a.md").read_text(encoding="utf-8") == "hi"
    # 第二次调模型时历史里应含 assistant(tool_calls) 与 tool 结果
    second = sent[1]
    assert any(m.get("role") == "tool" for m in second)
    assert any(m.get("tool_calls") for m in second)


def test_tool_loop_denied_tool_feeds_error_back(root: pathlib.Path) -> None:
    """面外工具 → deny 折成错误消息回灌，环不炸、模型改道。"""
    replies = [
        _FakeReply(tool_calls=[{"id": "c1", "name": "FileWrite", "args": {"path": "a.md", "content": "x"}}]),
        _FakeReply(text="改主意了"),
    ]
    seen_errors: list[str] = []

    def complete(messages, definitions):
        for message in messages:
            if message.get("role") == "tool":
                seen_errors.append(str(message.get("content")))
        return replies.pop(0)

    from functools import partial

    loop = ToolLoop(role=ASK_AGENT, runner=partial(execute, root))
    outcome = loop.run(complete, [{"role": "user", "content": "写文件"}])
    assert outcome.text == "改主意了"
    assert outcome.invocations[0].ok is False
    assert any("不在角色" in error for error in seen_errors)
    assert not (root / "a.md").exists()


def test_tool_loop_exhausts_at_max_iterations(root: pathlib.Path) -> None:
    """模型每轮都调工具 → 到封顶转 exhausted（不无限循环）。"""
    call = {"id": "c", "name": "Glob", "args": {"pattern": "*"}}

    def complete(messages, definitions):
        return _FakeReply(tool_calls=[call])

    from functools import partial

    loop = ToolLoop(role=BUILDER, runner=partial(execute, root))
    outcome = loop.run(complete, [{"role": "user", "content": "找文件"}])
    assert outcome.exhausted is True
    assert len(outcome.invocations) == MAX_TOOL_ITERATIONS


def test_tool_loop_tool_exception_becomes_error_not_crash(root: pathlib.Path) -> None:
    """工具抛异常 → 折成错误消息，环继续。"""
    replies = [
        _FakeReply(tool_calls=[{"id": "c1", "name": "FileRead", "args": {"path": "missing.md"}}]),
        _FakeReply(text="文件不在，我改用别的办法"),
    ]

    def complete(messages, definitions):
        return replies.pop(0)

    from functools import partial

    loop = ToolLoop(role=BUILDER, runner=partial(execute, root))
    outcome = loop.run(complete, [{"role": "user", "content": "读文件"}])
    assert outcome.text.startswith("文件不在")
    assert outcome.invocations[0].ok is False
    assert "错误" in outcome.invocations[0].result


def test_tool_loop_summary_line(root: pathlib.Path) -> None:
    replies = [
        _FakeReply(tool_calls=[{"id": "c1", "name": "Glob", "args": {"pattern": "*"}}]),
        _FakeReply(text="ok"),
    ]
    from functools import partial

    loop = ToolLoop(role=BUILDER, runner=partial(execute, root))
    outcome = loop.run(lambda m, d: replies.pop(0), [{"role": "user", "content": "x"}])
    assert "工具调用 1 次" in outcome.summary
    assert "Glob" in outcome.summary


def test_tool_loop_no_tools_returns_plain_text(root: pathlib.Path) -> None:
    from functools import partial

    loop = ToolLoop(role=BUILDER, runner=partial(execute, root))
    outcome = loop.run(lambda m, d: _FakeReply(text="直接答"), [{"role": "user", "content": "x"}])
    assert outcome.text == "直接答"
    assert outcome.invocations == []
    assert outcome.summary == ""


def test_registry_second_check_blocks_hallucinated_tool(root: pathlib.Path) -> None:
    """模型幻觉造工具名 → registry 第二道拦下。"""
    replies = [
        _FakeReply(tool_calls=[{"id": "c1", "name": "SuperDelete", "args": {}}]),
        _FakeReply(text="罢了"),
    ]
    from functools import partial

    loop = ToolLoop(role=BUILDER, runner=partial(execute, root))
    outcome = loop.run(lambda m, d: replies.pop(0), [{"role": "user", "content": "x"}])
    assert outcome.invocations[0].ok is False
    assert len(outcome.invocations) == 1
