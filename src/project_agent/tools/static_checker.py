"""静态正则检查器：8 类形态学检查，凌驾于白名单与两旋钮之上（deny 全档生效）。

判定顺序即模块内注册顺序（全 DENY，rule_id=static.<类名>）：
1. catastrophic_delete  灾难删除（rm/rmdir/Remove-Item/ri/rd + 递归 flag + 关键目标）
2. download_exec        下载即执行（管道链中下载器段 → 更后解释器段）
3. privilege_escalation 提权（剥壳后段首 sudo/doas/su/runas）
4. credentials          凭证面（段文本含敏感路径形态）
5. git_irreversible     git 不可逆（push -f/reset --hard/clean -f…d/checkout -- /restore -- /stash drop|clear/commit --amend）
6. network_egress       网络出口（URL host / scp host 不在域名白名单）
7. redirect             重定向（> >> < 目标为保护路径或可写根外绝对路径）
8. command_substitution 命令替换（段含 $( 或反引号）

不保证（调研 §10.3，5 条留人工）：
1. 形态学会漏——find -delete、脚本内部逻辑、未枚举的删除命令等不在上述形态内；
2. 引号内字面量会误伤——如 echo ".env 备份说明" 会被凭证类命中（fail-closed 方向）；
3. --force 含字母 r 会误中递归 flag 判定（同样 fail-closed 方向）；
4. PowerShell 反引号是转义符，会被命令替换类误伤（fail-closed 方向）；
5. 语义级风险留人工——外发内容审查、供应链 postinstall、不可解析目标、对话内
   口头边界、注入语料（本层一概不判）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .decision import Decision, DecisionAction
from .knobs import ShellKnobs

# ---- 拆段：操作符分隔符（括号深度>0 不拆；子 shell 剥外层括号递归拆）----
_OPERATOR_RE = re.compile(r"&&|\|\||;|\||\|&|&|\n")

# ---- 剥壳 wrapper：前导 env 赋值 + 前缀命令及其 flag/数字参数 ----
_WRAPPERS = frozenset(
    {"timeout", "nice", "nohup", "stdbuf", "command", "builtin", "noglob", "env"}
)
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(\"[^\"]*\"|'[^']*'|\S*)\s*")
_WRAPPER_TOKEN_RE = re.compile(
    r"^(?P<prog>[A-Za-z_][\w.-]*)\s+(?P<rest>\S.*)$", re.DOTALL
)

# ---- 类 1：灾难删除 ----
_DELETE_PROGRAMS = frozenset({"rm", "rmdir", "remove-item", "ri", "rd", "del"})
# 递归 flag：短簇含 r（-rf/-fr/-r/-Rf…）或 --recursive；--force 含字母 r 会误中——
# fail-closed 方向，文档化于模块 docstring。
_RECURSIVE_FLAG_RE = re.compile(r"(?<![\w-])-[\w]*[rR][\w]*(?![\w-])|--recursive|--recursion", re.IGNORECASE)
_CRITICAL_TARGET_RE = re.compile(
    r"(?<![\w~$.])~(?![\w.-]*\s)|(?<![\w])\.\.(?![\w])|(?<![\w])\*(?![\w])"
    r"|\$(?:\{|[A-Za-z_])|\$\("
    r"|(?<![\w])/|(?<![\w])\\|^[A-Za-z]:[\\/]?"
)
_DELETE_HEAD_RE = re.compile(r"^(?P<prog>[\w.-]+)\s+(?P<rest>.+)$", re.DOTALL)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]?")
_UNC_RE = re.compile(r"^\\\\")
_SENSITIVE_PATH_RE = re.compile(
    r"\.ssh\b|\.aws\b|\.gnupg\b|\.env\b|\.pem\b|id_rsa\b|id_ed25519\b|id_ecdsa\b"
    r"|\.npmrc\b|\.gitconfig\b|\.bashrc\b|\.zshrc\b|\.netrc\b|\.git/"
)

# ---- 类 2：下载即执行 ----
_DOWNLOADERS = frozenset({"curl", "wget", "fetch", "iwr", "invoke-webrequest"})
_INTERPRETERS = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "python",
        "python3",
        "perl",
        "ruby",
        "node",
        "pwsh",
        "powershell",
    }
)
_PRIV_PREFIX_RE = re.compile(r"^(sudo|doas|su|runas)\b", re.IGNORECASE)

# ---- 类 5：git 不可逆 ----
_GIT_IRREVERSIBLE_PATTERNS = (
    re.compile(r"\bgit\s+[^|;&]*?push\s+(-f\b|--force\b)", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?push\s+--force-with-lease\b", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?clean\s+-[a-z]*f[a-z]*d", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?clean\s+-[a-z]*d[a-z]*f", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?checkout\s+--\s", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?restore\s+--\s", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?stash\s+(drop|clear)\b", re.IGNORECASE),
    re.compile(r"\bgit\s+[^|;&]*?commit\s+--amend\b", re.IGNORECASE),
)

# ---- 类 6：网络出口 ----
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:[^/@\s]+@)?([^/:@\s]+)")
_SCP_RE = re.compile(r"\b(?:[\w.-]+@)([\w.-]+):(?![/\\])")
_DEFAULT_ALLOWED_DOMAINS = frozenset(
    {"registry.npmjs.org", "registry.npmmirror.com", "github.com"}
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# ---- 类 7：重定向 ----
_REDIRECT_TOKEN_RE = re.compile(r"(?<!\d)(>>|>|<)(?!&\d)")
_PROTECTED_REDIRECT_RE = re.compile(
    r"\.ssh\b|\.aws\b|\.gnupg\b|\.env\b|\.pem\b|id_rsa\b|id_ed25519\b|id_ecdsa\b"
    r"|\.npmrc\b|\.gitconfig\b|\.bashrc\b|\.zshrc\b|\.netrc\b|\.git/|\.git\\"
)


class ParseError(ValueError):
    """命令解析失败（悬空操作符/引号/括号不平衡）→ fail-closed = ask。"""


@dataclass(frozen=True)
class Segment:
    """拆出的一个命令段：原文 + 剥壳后的程序名。"""

    text: str
    program: str


def _check_quotes_parens(text: str) -> None:
    """引号/括号平衡检查：不平衡 → ParseError。"""
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            elif quote == '"' and ch == "\\":
                i += 1  # 双引号内转义跳过下一字符
        elif ch in {"'", '"'}:
            quote = ch
        elif ch in {"(", "["}:
            depth += 1
        elif ch in {")", "]"}:
            if depth == 0:
                raise ParseError(f"括号不平衡: {text!r}")
            depth -= 1
        i += 1
    if quote is not None:
        raise ParseError(f"引号不平衡: {text!r}")
    if depth != 0:
        raise ParseError(f"括号不平衡: {text!r}")


def parse_command(command: str) -> list[Segment]:
    """按 shell 操作符拆段（引号/括号感知；子 shell 剥外层括号递归拆）。

    悬空操作符（如 "npm test &&"）→ ParseError。
    """
    _check_quotes_parens(command)
    return _split_segments(command)


def _split_segments(text: str) -> list[Segment]:
    segments: list[Segment] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    pending_operator = False
    while i < len(text):
        ch = text[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            elif quote == '"' and ch == "\\" and i + 1 < len(text):
                current.append(text[i + 1])
                i += 1
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch in {"(", "["}:
            depth += 1
            current.append(ch)
            i += 1
            continue
        if ch in {")", "]"}:
            depth -= 1
            current.append(ch)
            i += 1
            continue
        if depth == 0:
            matched = None
            for length in (2, 1):
                token = text[i : i + length]
                if token in {"&&", "||", "|&", ";", "|", "&", "\n"}:
                    matched = token
                    break
            if matched:
                piece = "".join(current).strip()
                if not piece:
                    raise ParseError(f"悬空操作符: {text!r}")
                segments.extend(_emit(piece))
                current = []
                pending_operator = True
                i += len(matched)
                continue
        current.append(ch)
        i += 1
    piece = "".join(current).strip()
    if not piece:
        if pending_operator or segments:
            raise ParseError(f"悬空操作符: {text!r}")
        return []
    segments.extend(_emit(piece))
    return segments


def _emit(piece: str) -> list[Segment]:
    """一个操作符间片段 → Segment 列表（子 shell 剥外层括号递归拆）。"""
    stripped = piece
    while (
        stripped.startswith("(")
        and stripped.endswith(")")
        and _outer_parens_balanced(stripped)
    ):
        inner = stripped[1:-1].strip()
        if not inner:
            raise ParseError(f"空子 shell: {piece!r}")
        stripped = inner
    if not stripped:
        raise ParseError(f"空段: {piece!r}")
    return _split_segments(stripped) if stripped != piece else [_plain(stripped)]


def _outer_parens_balanced(text: str) -> bool:
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            elif quote == '"' and ch == "\\":
                i += 1
        elif ch in {"'", '"'}:
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(text) - 1:
                return False
        i += 1
    return depth == 0


def _plain(stripped: str) -> Segment:
    return Segment(text=stripped, program=program_of(stripped))


def program_of(segment_text: str) -> str:
    """段的程序名：跳过前导 sudo/doas/su/runas 与剥壳 wrapper，取首 token。"""
    text = segment_text.strip()
    while True:
        match = re.match(r"^(sudo|doas|su|runas)\s+(\S.*)$", text, re.IGNORECASE)
        if match:
            text = match.group(2)
            continue
        assign = _ENV_ASSIGN_RE.match(text)
        if assign:
            text = text[assign.end() :]
            continue
        head = re.match(r"^(?P<prog>[A-Za-z_][\w.-]*)\s+(?P<rest>\S.*)$", text, re.DOTALL)
        if head and head.group("prog").lower() in _WRAPPERS:
            text = head.group("rest")
            continue
        break
    first = text.split(None, 1)[0] if text.split(None, 1) else ""
    return first


def strip_wrappers(segment_text: str) -> str:
    """剥掉前导 env 赋值与 wrapper 命令（含其 flag/数字参数），返回剩余文本。"""
    text = segment_text.strip()
    while True:
        assign = _ENV_ASSIGN_RE.match(text)
        if assign:
            text = text[assign.end() :]
            continue
        match = _WRAPPER_TOKEN_RE.match(text)
        if match and match.group("prog").lower() in _WRAPPERS:
            rest = match.group("rest")
            skip = _skip_wrapper_args(match.group("prog").lower(), rest)
            text = rest[skip:].strip()
            continue
        break
    return text


def _skip_wrapper_args(prog: str, rest: str) -> int:
    """跳过 wrapper 自身的 flag/数字参数（timeout 30 / nice -n 10 / stdbuf -oL …）。

    env 较特殊：跳过 flag 后遇到的第一个非 flag token 可能仍是赋值，
    由外层循环继续剥；其余 wrapper 遇到第一个非 flag/非数字 token 即停。
    """
    pos = 0
    while pos < len(rest):
        token_match = re.match(r"\s*(?P<tok>\S+)", rest[pos:])
        if not token_match:
            break
        tok = token_match.group("tok")
        if prog == "env" and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            return pos  # 交给外层赋值剥壳循环
        if tok.startswith("-"):
            pos += token_match.end()
            continue
        if tok.isdigit():
            pos += token_match.end()
            continue
        break
    return pos


@dataclass(frozen=True)
class StaticCheckResult:
    """静态检查命中：类名 + 触发段。"""

    category: str
    segment: str


class StaticChecker:
    """8 类形态学检查器：任一段命中即 DENY（独立于白名单与两旋钮）。"""

    def __init__(self, allowed_domains: frozenset[str] | None = None) -> None:
        self._domains = (
            allowed_domains if allowed_domains is not None else _DEFAULT_ALLOWED_DOMAINS
        )

    def check(self, command: str) -> Decision | None:
        """整条命令检查：命中返回 deny Decision，未命中返回 None。"""
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
        # 类 2 需要管道链结构：用原始拆段文本（不剥子 shell 括号）建链
        chain = _operator_chain(command)
        hit = self._check_chain_download_exec(chain)
        if hit is not None:
            return self._deny(hit)
        for seg in segments:
            for category in _CHECK_FUNCS:
                if category(self, seg):
                    return self._deny(StaticCheckResult(category.__name__, seg.text))
        return None

    def _deny(self, hit: StaticCheckResult) -> Decision:
        return Decision(
            action=DecisionAction.DENY,
            rule_id=f"static.{hit.category}",
            reason=f"命中静态正则检查器 {hit.category} 类（形态学危险，全档拦截）",
            command=self._command,
            segment=hit.segment,
        )

    def _check_chain_download_exec(
        self, chain: list[list[str]]
    ) -> StaticCheckResult | None:
        """管道链（| 或 |& 连接的连续段）中：下载器段 → 更后解释器段。"""
        for pipe in chain:
            programs = [program_of(s) for s in pipe]
            for i, prog in enumerate(programs):
                if prog.lower() in _DOWNLOADERS:
                    for later in programs[i + 1 :]:
                        if later.lower() in _INTERPRETERS:
                            first_seg = pipe[i]
                            return StaticCheckResult(
                                "download_exec", first_seg
                            )
        return None


def _operator_chain(command: str) -> list[list[str]]:
    """按操作符拆出"管道链"列表：&& || ; & 换行 断链，| |& 链内成组。"""
    _check_quotes_parens(command)
    chains: list[list[str]] = []
    pipe: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0

    def flush_pipe() -> None:
        nonlocal pipe, current
        piece = "".join(current).strip()
        if piece:
            pipe.append(piece)
        current = []

    def flush_chain() -> None:
        nonlocal pipe
        flush_pipe()
        if pipe:
            chains.append(pipe)
        pipe = []

    while i < len(command):
        ch = command[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            elif quote == '"' and ch == "\\" and i + 1 < len(command):
                current.append(command[i + 1])
                i += 1
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch in {"(", "["}:
            depth += 1
            current.append(ch)
            i += 1
            continue
        if ch in {")", "]"}:
            depth -= 1
            current.append(ch)
            i += 1
            continue
        if depth == 0:
            two = command[i : i + 2]
            if two in {"&&", "||", "|&"}:
                flush_pipe()
                if two in {"&&", "||"}:
                    flush_chain()
                i += 2
                continue
            if ch in {";", "&", "\n"}:
                flush_chain()
                i += 1
                continue
            if ch == "|":
                flush_pipe()
                i += 1
                continue
        current.append(ch)
        i += 1
    flush_chain()
    return chains


# ---- 8 类检查函数（判定顺序即此序；self 为 StaticChecker 实例）----

def catastrophic_delete(self: StaticChecker, seg: Segment) -> bool:
    prog = seg.program.lower()
    if prog not in _DELETE_PROGRAMS:
        return False
    stripped = strip_wrappers(seg.text)
    rest = stripped.split(None, 1)
    rest_text = rest[1] if len(rest) > 1 else ""
    if not _RECURSIVE_FLAG_RE.search(rest_text):
        return False
    for tok in _tokenize(rest_text):
        if tok.startswith("-"):
            continue
        if _is_critical_target(tok):
            return True
    return False


def download_exec(self: StaticChecker, seg: Segment) -> bool:
    # 管道链结构在 check() 内统一判定（_check_chain_download_exec）
    return False


def privilege_escalation(self: StaticChecker, seg: Segment) -> bool:
    return bool(_PRIV_PREFIX_RE.match(strip_wrappers(seg.text)))


def credentials(self: StaticChecker, seg: Segment) -> bool:
    return bool(_SENSITIVE_PATH_RE.search(seg.text))


def git_irreversible(self: StaticChecker, seg: Segment) -> bool:
    return any(p.search(seg.text) for p in _GIT_IRREVERSIBLE_PATTERNS)


def network_egress(self: StaticChecker, seg: Segment) -> bool:
    hosts = _extract_hosts(seg.text)
    for host in hosts:
        if host.lower() in _LOCAL_HOSTS:
            continue
        if not _domain_allowed(host.lower(), self._domains):
            return True
    return False


def redirect(self: StaticChecker, seg: Segment) -> bool:
    for m in _REDIRECT_TOKEN_RE.finditer(seg.text):
        op = m.group(1)
        after = seg.text[m.end() :]
        tok = _first_token(after)
        if tok is None:
            return False
        if tok in {"/dev/null", "NUL", "nul"}:
            continue
        if _PROTECTED_REDIRECT_RE.search(tok):
            return True
        if _is_outside_writable(tok, self._workspace_roots):
            return True
        del op
    return False


def command_substitution(self: StaticChecker, seg: Segment) -> bool:
    return "$(" in seg.text or "`" in seg.text


_CHECK_FUNCS = (
    catastrophic_delete,
    download_exec,
    privilege_escalation,
    credentials,
    git_irreversible,
    network_egress,
    redirect,
    command_substitution,
)


def _tokenize(text: str) -> list[str]:
    """粗粒度 token 化（够形态学判定用；引号内空格不进一步拆）。"""
    tokens: list[str] = []
    quote: str | None = None
    current: list[str] = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in {"'", '"'}:
            quote = ch
            current.append(ch)
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _first_token(text: str) -> str | None:
    stripped = text.lstrip()
    if not stripped:
        return None
    return stripped.split(None, 1)[0]


def _is_critical_target(tok: str) -> bool:
    """关键目标：~、..、裸 *、$VAR/${/$(、token 首 /、盘根 X:、UNC、根外绝对路径、token 首反斜杠。"""
    if not tok:
        return False
    body = tok.strip("'\"")
    if body in {"~", ".."} or body.startswith("~/") or body.startswith("..\\") or body.startswith("../"):
        return True
    if body == "*" or body.startswith("/*") or body == "*" + "/":
        return True
    if "$" in body:
        return True
    if body.startswith("/"):
        return True
    if _UNC_RE.match(body):
        return True
    if _WINDOWS_DRIVE_RE.match(body):
        return True
    if body.startswith("\\"):
        return True
    return False


def _extract_hosts(segment_text: str) -> list[str]:
    hosts: list[str] = []
    for m in _URL_RE.finditer(segment_text):
        hosts.append(m.group(1))
    for m in _SCP_RE.finditer(segment_text):
        hosts.append(m.group(1))
    return hosts


def _domain_allowed(host: str, domains: frozenset[str]) -> bool:
    if host in domains:
        return True
    return any(
        host.endswith("." + d) or host == d for d in domains
    )


def _is_outside_writable(tok: str, roots: tuple[tuple[str, str], ...]) -> bool:
    """重定向目标绝对路径是否在可写根外（~ 前缀 token 视为根外）。"""
    body = tok.strip("'\"")
    if body.startswith("~"):
        return True
    if not (body.startswith("/") or _WINDOWS_DRIVE_RE.match(body) or _UNC_RE.match(body)):
        return False
    if body in {"/dev/null", "NUL", "nul"}:
        return False
    for root_win, root_posix in roots:
        for root in (root_win, root_posix):
            if not root:
                continue
            if body == root or body.startswith(root + "/") or body.startswith(root + "\\"):
                return False
    return True


__all__ = [
    "ParseError",
    "Segment",
    "StaticChecker",
    "parse_command",
    "program_of",
    "strip_wrappers",
]
