"""工具实现层（17 票）：六件文件类工具的真实本体。

设计边界：
- **只做执行**，不做权限判定——权限由 `ToolRegistry`（构造期面裁剪 + 二次 check）
  与 `ShellPolicy`（命令内容）负责；本层假定"调用方已判定 allow"。
- **路径受控**：全部经 `_safe_path` 归一到 workspace_root 内，拒 `..` 与绝对路径
  越界（与 `frontend_launcher` 同法的三重检查）。
- **错误即返回值**：工具失败抛异常，由回路层捕获折成 `tool` 错误消息——本层不吞错。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

_GLOB_LIMIT = 200
_GREP_LIMIT = 50
_READ_LIMIT_DEFAULT = 2000


class ToolError(Exception):
    """工具执行失败（路径越界 / 文件不存在 / 编辑不唯一等）。"""


@dataclass(frozen=True)
class ToolResult:
    """一次工具执行的结果：`content` 回灌给模型，`ok` 供回路层统计。"""

    content: str
    ok: bool = True


def _safe_path(root: Path, raw: str) -> Path:
    """把用户/模型给的路径归一到 root 内；越界抛 ToolError。

    三重检查（与 frontend_launcher 同法）：绝对路径前缀、盘符、`..` 片段。
    相对路径正常解析到 root 下。
    """
    text = str(raw or "").strip()
    if not text:
        raise ToolError("路径为空")
    normalized = text.replace("\\", "/")
    if normalized.startswith("/"):
        raise ToolError(f"不接受绝对路径: {raw}")
    first = normalized.split("/", 1)[0]
    if ":" in first:
        raise ToolError(f"不接受绝对路径: {raw}")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if ".." in parts:
        raise ToolError(f"不接受父目录引用: {raw}")
    resolved_root = Path(root).resolve()
    target = (resolved_root.joinpath(*parts) if parts else resolved_root).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ToolError(f"路径越出工作区: {raw}") from exc
    return target


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


# ---- FileRead ----

def file_read(root: Path, path: str, offset: int = 1, limit: int = _READ_LIMIT_DEFAULT) -> str:
    """读文本文件（UTF-8，BOM 剥），支持 offset/limit（1-based 行号）。"""
    target = _safe_path(root, path)
    if not target.exists():
        raise ToolError(f"文件不存在: {path}")
    if target.is_dir():
        raise ToolError(f"是目录不是文件: {path}")
    try:
        text = target.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ToolError(f"非 UTF-8 文本: {path}") from exc
    lines = text.splitlines()
    start = max(0, int(offset) - 1)
    end = start + max(1, int(limit))
    chunk = lines[start:end]
    if not chunk:
        return f"（{path} 共 {len(lines)} 行，offset={offset} 起无内容）"
    numbered = [f"{start + index + 1}\t{line}" for index, line in enumerate(chunk)]
    header = f"（{_relative(root, target)} 第 {start + 1}-{start + len(chunk)} 行 / 共 {len(lines)} 行）"
    return header + "\n" + "\n".join(numbered)


# ---- Glob ----

def glob_files(root: Path, pattern: str) -> str:
    """按 glob 模式找文件（相对 workspace_root），返回相对路径列表。"""
    text = str(pattern or "").strip()
    if not text:
        raise ToolError("pattern 为空")
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/", 1)[0]:
        raise ToolError(f"不接受绝对路径模式: {pattern}")
    if ".." in [part for part in normalized.split("/") if part]:
        raise ToolError(f"不接受父目录引用: {pattern}")
    matches = sorted(
        _relative(root, item) for item in Path(root).resolve().glob(normalized) if item.is_file()
    )
    if not matches:
        return f"（无匹配: {pattern}）"
    shown = matches[:_GLOB_LIMIT]
    suffix = "" if len(matches) <= _GLOB_LIMIT else f"\n（共 {len(matches)} 个，仅列前 {_GLOB_LIMIT}）"
    return "\n".join(shown) + suffix


# ---- Grep ----

def grep_files(root: Path, pattern: str, path: str = ".", ignore_case: bool = False) -> str:
    """正则搜索文件内容，返回 `文件:行:内容`（封顶 50 条）。"""
    text = str(pattern or "")
    if not text:
        raise ToolError("pattern 为空")
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(text, flags)
    except re.error as exc:
        raise ToolError(f"正则非法: {exc}") from exc

    base = _safe_path(root, path)
    if not base.exists():
        raise ToolError(f"路径不存在: {path}")
    candidates = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
    hits: list[str] = []
    for candidate in candidates:
        try:
            content = candidate.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{_relative(root, candidate)}:{number}:{line.strip()[:200]}")
                if len(hits) >= _GREP_LIMIT:
                    return "\n".join(hits) + f"\n（已达上限 {_GREP_LIMIT} 条，请缩小范围）"
    return "\n".join(hits) if hits else f"（无匹配: {pattern}）"


# ---- FileWrite ----

def file_write(root: Path, path: str, content: str) -> str:
    """全量写（父目录自动建；统一 UTF-8 无 BOM、LF 行尾）。"""
    target = _safe_path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content), encoding="utf-8", newline="\n")
    lines = str(content).count("\n") + (0 if str(content).endswith("\n") else 1)
    return f"已写入 {_relative(root, target)}（{lines} 行）"


# ---- FileEdit ----

def file_edit(root: Path, path: str, old: str, new: str) -> str:
    """字面量替换：`old` 必须**恰好命中一次**，否则报错（不猜、不批量）。"""
    target = _safe_path(root, path)
    if not target.exists():
        raise ToolError(f"文件不存在: {path}")
    text = target.read_text(encoding="utf-8-sig")
    occurrences = text.count(old)
    if occurrences == 0:
        raise ToolError(f"未找到待替换文本（old 未命中）: {path}")
    if occurrences > 1:
        raise ToolError(f"待替换文本命中 {occurrences} 处（必须唯一，请提供更长上下文）: {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    return f"已编辑 {_relative(root, target)}（替换 1 处）"


# ---- DocScaffold ----

#: 各构建方式的交付物骨架（spec『交付』交付物集定义表——只建骨架不写内容）
_SCAFFOLD_TITLES: dict[str, dict[str, str]] = {
    "way2": {"IDEA.md": "# 想法\n\n"},
    "way3": {
        "README.md": "# 项目名\n\n## 是什么\n\n## 怎么用\n\n",
        "TODO.md": "# TODO\n\n## 待办\n\n## 完成\n\n",
        "目录树.txt": "项目目录结构：\n\n",
    },
    "way4": {
        "README.md": "# 项目名\n\n## 是什么\n\n## 怎么用\n\n",
        "TODO.md": "# TODO\n\n## 待办\n\n## 完成\n\n",
        "目录树.txt": "项目目录结构：\n\n",
        "docs/需求规格.md": "# 需求规格\n\n",
        "docs/技术选型.md": "# 技术选型\n\n",
        "docs/目录结构.md": "# 目录结构\n\n",
    },
}


def doc_scaffold(root: Path, build_way: str, path: str = "") -> str:
    """按构建方式产出交付物骨架（已存在则跳过，不覆盖用户内容）。"""
    way = str(build_way or "").strip()
    templates = _SCAFFOLD_TITLES.get(way)
    if not templates:
        return f"（{way or '未指定'} 无交付物骨架）"
    created: list[str] = []
    skipped: list[str] = []
    for name, body in templates.items():
        if path.strip():
            target = _safe_path(root, str(Path(path) / name))
        else:
            target = _safe_path(root, name)
        if target.exists():
            skipped.append(_relative(root, target))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="\n")
        created.append(_relative(root, target))
    parts = []
    if created:
        parts.append("已创建: " + "、".join(created))
    if skipped:
        parts.append("已存在跳过: " + "、".join(skipped))
    return "\n".join(parts) if parts else "（无动作）"


# ---- 分派表（工具名 → 调用）----

#: 工具名 → 执行函数；参数名与 `tool_definitions` 的 schema 属性名严格一致。
EXECUTORS: dict[str, Callable[..., str]] = {
    "FileRead": file_read,
    "Glob": glob_files,
    "Grep": grep_files,
    "FileWrite": file_write,
    "FileEdit": file_edit,
    "DocScaffold": doc_scaffold,
}


def execute(root: Path, tool: str, arguments: Mapping[str, Any]) -> ToolResult:
    """执行一次工具调用；未知工具/参数不符/执行异常 → ToolResult(ok=False)。"""
    executor = EXECUTORS.get(tool)
    if executor is None:
        return ToolResult(content=f"错误：工具 {tool} 不在可执行集合内", ok=False)
    try:
        return ToolResult(content=executor(root, **dict(arguments)), ok=True)
    except ToolError as exc:
        return ToolResult(content=f"错误：{exc}", ok=False)
    except TypeError as exc:
        return ToolResult(content=f"错误：{tool} 参数不符（{exc}）", ok=False)
    except Exception as exc:  # noqa: BLE001 - 工具异常一律回灌给模型，不中断环
        return ToolResult(content=f"错误：{tool} 执行失败（{type(exc).__name__}: {exc}）", ok=False)


__all__ = [
    "EXECUTORS",
    "ToolError",
    "ToolResult",
    "doc_scaffold",
    "execute",
    "file_edit",
    "file_read",
    "file_write",
    "glob_files",
    "grep_files",
]
