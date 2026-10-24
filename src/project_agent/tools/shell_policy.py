"""shell 权限策略：静态检查 → 白名单 → boundary → interrupt 的判定管线。

决策序（spec『工具权限』节 + 调研 §10.1/§10.4）：
1. 解析失败 → ask(rule=parse.failure)（fail-closed）；
2. 静态 8 类任一段命中 → deny（全档生效，allow 命中也拦，yolo 不豁免）；
3. 白名单逐段：deny > ask > allow（先匹配先赢）；allow 分 read/write 两节，
   boundary=readonly 只认 read 节；模式含 * 转 ^….*$ 全匹配，尾缀 " *" 还匹配裸命令；
4. boundary：readonly——仅 read-allow 命中段放行，其余段 deny(boundary.readonly)；
   project-write——allow_write 命中段含可写根外绝对路径 token → deny(boundary.outside_workspace)；
   full——跳过；
5. interrupt：human——全部非 deny 段 → ask；yolo——全部非 deny 段 → allow；
   ai——allow 命中 → allow，ask 命中或未命中 → ask；
6. 跨段聚合取最重（deny > ask > allow），Decision 带首个最重段的 segment。

可写根 =（workspace_root, tempfile.gettempdir()）；路径含 ~ 前缀 token 视为根外。

不保证（调研 §10.3）：白名单是文本前缀/通配语义——`git -C . push` 这类选项重排
不会命中 `git push *`；语义级外发、供应链、不可解析目标留人工。
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .decision import Decision, DecisionAction, merge_decisions
from .knobs import Boundary, Interrupt, ShellKnobs
from .static_checker import (
    ParseError,
    Segment,
    StaticChecker,
    parse_command,
    program_of,
)

_POLICY_JSON = Path(__file__).with_name("shell_policy.json")
_DEFAULT_POLICY_PATH = _POLICY_JSON


@dataclass(frozen=True)
class WhitelistRules:
    """白名单规则集：allow 分 read/write 两节 + ask + deny。

    模式语法：文本通配——模式含 * 时转为 ^<前缀>.*$ 全匹配（* 匹配任意文本含空格）；
    尾缀 " *"（带空格）还匹配裸命令本身（"ls *" 也放行 "ls"）。
    """

    allow_read: tuple[str, ...] = ()
    allow_write: tuple[str, ...] = ()
    ask: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = (
        "registry.npmjs.org",
        "registry.npmmirror.com",
        "github.com",
    )
    allow_localhost: bool = True


@dataclass(frozen=True)
class _CompiledRule:
    action: DecisionAction
    rule_id: str
    reason: str
    regex: re.Pattern[str]
    bare_command: str | None  # 尾缀 " *" 模式对应的裸命令（"ls *" → "ls"）


class ShellPolicy:
    """判定管线入口：check(command) -> Decision。"""

    def __init__(
        self,
        knobs: ShellKnobs,
        workspace_root: str | Path,
        rules: WhitelistRules | None = None,
    ) -> None:
        self._knobs = knobs
        self._workspace_root = _normalize_root(workspace_root)
        self._rules = rules if rules is not None else load_rules()
        self._checker = StaticChecker(
            allowed_domains=frozenset(self._rules.allowed_domains),
            workspace_roots=self._writable_roots(),
            allow_localhost=self._rules.allow_localhost,
        )
        self._compiled = _compile_rules(self._rules)

    def _writable_roots(self) -> tuple[str, ...]:
        return (self._workspace_root, _normalize_root(tempfile.gettempdir()))

    def check(self, command: str) -> Decision:
        """整条命令 → 聚合 Decision（跨段取最重，带首个最重段 segment）。"""
        try:
            segments = parse_command(command)
        except ParseError as exc:
            return Decision(
                action=DecisionAction.ASK,
                rule_id="parse.failure",
                reason=f"命令解析失败（fail-closed）: {exc}",
                command=command,
                segment=command,
            )
        static = self._checker.check(command)
        if static is not None and static.action is DecisionAction.DENY:
            return static
        results: list[tuple[str, Decision]] = []
        for seg in segments:
            results.append((seg.text, self._judge_segment(seg)))
        default = Decision(
            action=DecisionAction.ASK,
            rule_id="whitelist.miss",
            reason="命令不在白名单内（默认 ask）",
            command=command,
            segment=command,
        )
        return merge_decisions(results, default)

    def _judge_segment(self, seg: Segment) -> Decision:
        """单段判定：白名单 → boundary → interrupt。"""
        allow_hit = self._match_allow(seg)
        ask_hit = self._match_ask(seg)
        deny_hit = self._match_deny(seg)
        # 白名单序：deny > ask > allow
        if deny_hit is not None:
            return deny_hit
        if ask_hit is not None:
            return self._apply_interrupt(ask_hit, was_allow=False)
        if allow_hit is not None:
            # boundary：readonly 只认 read 节命中；project-write 查根外 token
            if self._knobs.boundary is Boundary.READONLY:
                if allow_hit.rule_id != "whitelist.allow_read":
                    return Decision(
                        action=DecisionAction.DENY,
                        rule_id="boundary.readonly",
                        reason="readonly 边界：仅只读白名单段可放行",
                        command=allow_hit.command,
                        segment=allow_hit.segment,
                    )
            elif self._knobs.boundary is Boundary.PROJECT_WRITE:
                if allow_hit.rule_id == "whitelist.allow_write" and self._segment_outside_workspace(seg):
                    return Decision(
                        action=DecisionAction.DENY,
                        rule_id="boundary.outside_workspace",
                        reason="project-write 边界：写类白名单段含可写根外绝对路径",
                        command=allow_hit.command,
                        segment=allow_hit.segment,
                    )
            return self._apply_interrupt(allow_hit, was_allow=True)
        # 未命中任何白名单节
        miss = Decision(
            action=DecisionAction.ASK,
            rule_id="whitelist.miss",
            reason="命令不在白名单内（默认 ask）",
            command=seg.text,
            segment=seg.text,
        )
        return self._apply_interrupt(miss, was_allow=False)

    def _apply_interrupt(self, decision: Decision, *, was_allow: bool) -> Decision:
        """interrupt 旋钮：human 全部非 deny → ask；yolo 全部非 deny → allow。"""
        if self._knobs.interrupt is Interrupt.HUMAN:
            if decision.action is DecisionAction.DENY:
                return decision
            return Decision(
                action=DecisionAction.ASK,
                rule_id="interrupt.human",
                reason="全权人工档：非 deny 段一律升级人工",
                command=decision.command,
                segment=decision.segment,
            )
        if self._knobs.interrupt is Interrupt.YOLO:
            if decision.action is DecisionAction.DENY:
                return decision
            return Decision(
                action=DecisionAction.ALLOW,
                rule_id="interrupt.yolo",
                reason="yolo 档：非 deny 段全部放行",
                command=decision.command,
                segment=decision.segment,
            )
        # ai_review：allow 命中 → allow；ask 命中或未命中 → ask
        if was_allow and decision.action is DecisionAction.ALLOW:
            return decision
        if decision.action is DecisionAction.DENY:
            return decision
        return Decision(
            action=DecisionAction.ASK,
            rule_id=decision.rule_id if decision.rule_id.startswith(("whitelist.", "boundary.")) else "interrupt.ai_review",
            reason=decision.reason if decision.rule_id.startswith(("whitelist.", "boundary.")) else "AI 审核档：ask 命中或未命中升级审核",
            command=decision.command,
            segment=decision.segment,
        )

    def _match_allow(self, seg: Segment) -> Decision | None:
        """allow 节匹配：先 write 节后 read 节（write 更宽，命中即用）。"""
        for section, rule_id in (
            ("allow_write", "whitelist.allow_write"),
            ("allow_read", "whitelist.allow_read"),
        ):
            patterns: tuple[str, ...] = getattr(self._rules, section)
            for pattern in patterns:
                if _matches(pattern, seg.text):
                    return Decision(
                        action=DecisionAction.ALLOW,
                        rule_id=rule_id,
                        reason=f"命中白名单 {section} 规则: {pattern}",
                        command=seg.text,
                        segment=seg.text,
                    )
        return None

    def _match_ask(self, seg: Segment) -> Decision | None:
        for pattern in self._rules.ask:
            if _matches(pattern, seg.text):
                return Decision(
                    action=DecisionAction.ASK,
                    rule_id="whitelist.ask",
                    reason=f"命中白名单 ask 规则: {pattern}",
                    command=seg.text,
                    segment=seg.text,
                )
        return None

    def _match_deny(self, seg: Segment) -> Decision | None:
        for pattern in self._rules.deny:
            if _matches(pattern, seg.text):
                return Decision(
                    action=DecisionAction.DENY,
                    rule_id="whitelist.deny",
                    reason=f"命中白名单 deny 规则: {pattern}",
                    command=seg.text,
                    segment=seg.text,
                )
        return None

    def _segment_outside_workspace(self, seg: Segment) -> bool:
        """段内是否含可写根外绝对路径 token（Windows 盘根/UNC/POSIX 绝对/~ 前缀）。"""
        for tok in _tokens(seg.text):
            if _outside_writable(tok, self._writable_roots()):
                return True
        return False


def _matches(pattern: str, text: str) -> bool:
    """白名单通配匹配：* → 任意文本（含空格）；尾缀 " *" 还匹配裸命令。"""
    if "*" in pattern:
        prefix = pattern.split("*", 1)[0]
        if not re.match(r"^" + re.escape(prefix) + r".*$", text, re.DOTALL):
            return False
        bare = pattern.endswith(" *")
        if bare and text == pattern[:-2]:
            return True
        return True
    return pattern == text


def _compile_rules(rules: WhitelistRules) -> dict[str, list[_CompiledRule]]:
    """预编译缓存（规则量小暂未启用，直接匹配；留接口供后续优化）。"""
    return {}


def _normalize_root(root: str | Path) -> str:
    text = str(root).replace("\\", "/")
    return text.casefold().rstrip("/") or "/"


def _tokens(segment_text: str) -> list[str]:
    parts = segment_text.split()
    return parts


def _outside_writable(tok: str, roots: tuple[str, ...]) -> bool:
    from .static_checker import _is_outside_writable as _sc_outside

    return _sc_outside(tok, roots)


def load_rules(path: Path | None = None) -> WhitelistRules:
    """从 JSON 加载白名单（调研 §10.2 草案改用：管道类 deny 已删——拆段后不可达；
    git clone 只留 ask；allow 拆 read/write 两节供 boundary 用）。"""
    source = path if path is not None else _DEFAULT_POLICY_PATH
    data = json.loads(source.read_text(encoding="utf-8"))
    boundary = data.get("boundary", {})
    network = boundary.get("network", {})
    return WhitelistRules(
        allow_read=tuple(data.get("allow_read", ())),
        allow_write=tuple(data.get("allow_write", ())),
        ask=tuple(data.get("ask", ())),
        deny=tuple(data.get("deny", ())),
        allowed_domains=tuple(
            network.get(
                "allowed_domains",
                ("registry.npmjs.org", "registry.npmmirror.com", "github.com"),
            )
        ),
        allow_localhost=bool(network.get("allow_localhost", True)),
    )


__all__ = ["ShellPolicy", "WhitelistRules", "load_rules"]
