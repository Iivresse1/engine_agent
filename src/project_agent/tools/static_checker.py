"""静态正则检查器：8 类形态学检查，凌驾于白名单与两旋钮之上（deny 全档生效）。

判定顺序即本模块注册顺序（全 DENY，rule_id=static.<类名>）：
1. catastrophic_delete  灾难删除（rm/rmdir/Remove-Item/ri/rd/del + 递归 flag + 关键目标）
2. download_exec        下载即执行（管道链中下载器段 → 更后解释器段）
3. privilege_escalation 提权（剥壳后段首 sudo/doas/su/runas，大小写不敏感）
4. credentials          凭证面（段文本含敏感路径形态）
5. git_irreversible     git 不可逆（push -f/--force[=lease]/reset --hard/clean -f…d/
                        checkout -- /restore -- /stash drop|clear/commit --amend）
6. network_egress       网络出口（URL host / scp host 不在域名白名单）
7. redirect             重定向（> >> < 目标为保护路径或可写根外绝对路径）
8. command_substitution 命令替换（段含 $( 或反引号）

不保证（调研 §10.3，5 条留人工/LLM——静态覆盖不了）：
1. 形态学会漏——find -delete、脚本内部逻辑、未枚举的删除/外发命令不在上述形态内；
2. 引号内字面量会误伤——echo ".env 说明" 这类普通文本会被凭证类命中（fail-closed 方向）；
3. --force 含字母 r 会误中递归 flag 判定、PowerShell 反引号是转义符会被命令替换类误伤
   （同样 fail-closed 方向，可接受）；
4. 语义级风险留人工——外发内容审查、供应链 postinstall、不可解析命令替换目标、
   对话内口头边界、注入语料，本层一概不判；
5. 域名白名单按 host 精确/子域后缀匹配，TLS 内容与 fronting 不在覆盖范围。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .decision import Decision, DecisionAction

# ---- 拆段与剥壳 ----
_WRAPPERS = frozenset(
    {"timeout", "nice", "nohup", "stdbuf", "command", "builtin", "noglob", "env"}
)
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(\"[^\"]*\"|'[^']*'|\S*)\s*")

# ---- 类 1：灾难删除 ----
_DELETE_PROGRAMS = frozenset({"rm", "rmdir", "remove-item", "ri", "rd", "del"})
_WINDOWS_DELETE_PROGRAMS = frozenset({"remove-item", "ri", "rd", "del"})
# 递归 flag：短簇含 r（-rf/-fr/-r…）或 --recursive；Windows 风格 /s（rd/del）。
# --force 含字母 r 会误中——fail-closed 方向，见模块 docstring 不保证清单。
_RECURSIVE_FLAG_RE = re.compile(
    r"(?<![\w-])-[\w]*[rR][\w]*(?![\w-])"
    r"|(?<![\w-])--recursive\b"
    r"|(?<![\w/])/[sS](?![\w])"
)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]?")
_UNC_RE = re.compile(r"^\\\\")

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
# 解释器内联脚本标志：-c / -e / -Command（其后引号串内含删除形态时按类 1 扫）
_INLINE_SCRIPT_FLAG = r"(?:-c|-e|-Command|--eval|--exec)"
_INLINE_DELETE_RE = re.compile(
    _INLINE_SCRIPT_FLAG + r"\s+(\"[^\"]*\"|'[^']*'|\"[^\"]*$|'[^']*$|\S+)",
    re.IGNORECASE,
)
_INLINE_RM_RE = re.compile(
    r"\b(?:rm|rmdir|Remove-Item|ri|rd|del)\b[^|;&\n]*?"
    r"(?<![\w-])(?:-[\w]*[rR][\w]*|--recursive)(?![\w-])",
    re.IGNORECASE,
)

# ---- 类 3：提权 ----
_PRIV_PREFIX_RE = re.compile(r"^(sudo|doas|su|runas)\b", re.IGNORECASE)
_PRIV_PREFIX_SKIP_RE = re.compile(r"^(sudo|doas|su|runas)\s+(?P<rest>\S.*)$", re.IGNORECASE | re.DOTALL)

# ---- 类 4：凭证面 ----
_SENSITIVE_PATH_RE = re.compile(
    r"\.ssh\b|\.aws\b|\.gnupg\b|\.env\b|\.pem\b|id_rsa\b|id_ed25519\b|id_ecdsa\b"
    r"|\.npmrc\b|\.gitconfig\b|\.bashrc\b|\.zshrc\b|\.netrc\b"
)

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
_SCP_RE = re.compile(r"(?:^|\s)(?:[\w.-]+@)([\w.-]+):")
_DEFAULT_ALLOWED_DOMAINS = frozenset(
    {"registry.npmjs.org", "registry.npmmirror.com", "github.com"}
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# ---- 类 7：重定向 ----
_REDIRECT_TOKEN_RE = re.compile(r"(?<!\d)(>>|>|<)(?!&?\d)")
_PROTECTED_REDIRECT_RE = re.compile(
    r"\.ssh\b|\.aws\b|\.gnupg\b|\.env\b|\.pem\b|id_rsa\b|id_ed25519\b|id_ecdsa\b"
    r"|\.npmrc\b|\.gitconfig\b|\.bashrc\b|\.zshrc\b|\.netrc\b|\.git[/\\]"
)
_NULL_DEVICES = frozenset({"/dev/null", "NUL", "nul"})


class ParseError(ValueError):
    """命令解析失败（悬空操作符/引号/括号不平衡）→ fail-closed = ask。"""


@dataclass(frozen=True)
class Segment:
    """拆出的一个命令段：原文 + 剥壳后的程序名。"""

    text: str
    program: str


def _scan(text: str):
    """单遍字符扫描状态机：返回 (带引号转义还原的文本, 操作符位置列表)。

    操作符位置为 (start, length)，仅在 depth==0 且引号外识别。
    """
    out: list[str] = []
    ops: list[tuple[int, int]] = []
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
                out.append(ch)
            elif quote == '"' and ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            else:
                out.append(ch)
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch in {"(", "["}:
            depth += 1
            out.append(ch)
            i += 1
            continue
        if ch in {")", "]"}:
            depth -= 1
            out.append(ch)
            i += 1
            continue
        if depth == 0:
            two = text[i : i + 2]
            if two in {"&&", "||", "|&"}:
                ops.append((i, 2))
                out.append("\0")
                i += 2
                continue
            if ch in {";", "|", "&", "\n"}:
                ops.append((i, 1))
                out.append("\0")
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out), ops


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
                i += 1
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


def _split_on_ops(command: str) -> list[str]:
    """按 depth-0 操作符切成片段文本（引号/括号感知；\0 作切分锚）。"""
    _check_quotes_parens(command)
    scanned, _ops = _scan(command)
    return [piece.strip() for piece in scanned.split("\0")]


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
    if stripped != piece:
        return _segments_from_pieces(_split_on_ops(stripped))
    return [Segment(text=stripped, program=program_of(stripped))]


def _segments_from_pieces(pieces: list[str]) -> list[Segment]:
    segments: list[Segment] = []
    for piece in pieces:
        if not piece:
            raise ParseError("悬空操作符")
        segments.extend(_emit(piece))
    if not segments:
        raise ParseError("空命令")
    return segments


def _outer_parens_balanced(text: str) -> bool:
    """text 是否恰为一对最外层括号包裹（( ... ) 且内部括号自平衡）。"""
    if not (text.startswith("(") and text.endswith(")")):
        return False
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


def parse_command(command: str) -> list[Segment]:
    """按 shell 操作符（&& || ; | |& & 换行）拆段；子 shell 剥外层括号递归拆。

    悬空操作符/引号/括号不平衡 → ParseError。
    """
    pieces = _split_on_ops(command)
    if not pieces or all(not p for p in pieces):
        if command.strip():
            raise ParseError(f"悬空操作符: {command!r}")
        raise ParseError("空命令")
    return _segments_from_pieces(pieces)


def program_of(segment_text: str) -> str:
    """段的程序名：跳过前导 sudo/doas/su/runas（含其 flag）与剥壳 wrapper。"""
    text = segment_text.strip()
    while True:
        match = _PRIV_PREFIX_SKIP_RE.match(text)
        if match:
            rest = match.group("rest")
            skip = _skip_flag_tokens(rest)
            text = rest[skip:].strip()
            continue
        assign = _ENV_ASSIGN_RE.match(text)
        if assign:
            text = text[assign.end() :]
            continue
        head = re.match(r"^(?P<prog>[A-Za-z_][\w.-]*)\s+(?P<rest>\S.*)$", text, re.DOTALL)
        if head and head.group("prog").lower() in _WRAPPERS:
            rest = head.group("rest")
            skip = _skip_wrapper_args(head.group("prog").lower(), rest)
            text = rest[skip:].strip()
            continue
        break
    parts = text.split(None, 1)
    return parts[0] if parts else ""


def _skip_flag_tokens(rest: str) -> int:
    """跳过前导 flag token（-x / /x 形式），返回已消费字符数。"""
    pos = 0
    while pos < len(rest):
        m = re.match(r"\s*(?P<tok>\S+)", rest[pos:])
        if not m:
            break
        tok = m.group("tok")
        if tok.startswith("-") or tok.startswith("/"):
            pos += m.end()
            continue
        break
    return pos


def strip_wrappers(segment_text: str) -> str:
    """剥掉前导 env 赋值与 wrapper 命令（含其 flag/数字参数），返回剩余文本。"""
    text = segment_text.strip()
    while True:
        assign = _ENV_ASSIGN_RE.match(text)
        if assign:
            text = text[assign.end() :]
            continue
        head = re.match(r"^(?P<prog>[A-Za-z_][\w.-]*)\s+(?P<rest>\S.*)$", text, re.DOTALL)
        if head and head.group("prog").lower() in _WRAPPERS:
            rest = head.group("rest")
            skip = _skip_wrapper_args(head.group("prog").lower(), rest)
            text = rest[skip:].strip()
            continue
        break
    return text


def _skip_wrapper_args(prog: str, rest: str) -> int:
    """跳过 wrapper 自身的 flag/数字参数（timeout 30 / nice -n 10 / stdbuf -oL）。

    env 特例：-u/--unset 这类带值 flag 连值一起跳；遇赋值 token 交外层循环。
    """
    pos = 0
    value_taking = False
    while pos < len(rest):
        m = re.match(r"\s*(?P<tok>\S+)", rest[pos:])
        if not m:
            break
        tok = m.group("tok")
        if prog == "env":
            if value_taking and "=" not in tok:
                value_taking = False
                pos += m.end()
                continue
            if tok in {"-u", "--unset"}:
                value_taking = True
                pos += m.end()
                continue
            if tok.startswith("-"):
                pos += m.end()
                continue
            break
        if tok.startswith("-") or tok.isdigit():
            pos += m.end()
            continue
        break
    return pos


def _operator_chains(command: str) -> list[list[str]]:
    """按操作符拆"管道链"：&& || ; & 换行断链，| |& 链内成组（深度感知）。"""
    scanned, ops = _scan(command)
    if scanned == command:
        text = scanned
    else:
        text = scanned
    del ops
    # 以 \0 为统一分隔符；链分隔符保留标记后重组
    pieces: list[str] = []
    chain_breaks: list[bool] = []  # 每个分隔符是否断链（&& || ; & 换行 = True）
    current: list[str] = []
    i = 0
    depth = 0
    quote: str | None = None
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
                pieces.append("".join(current))
                current = []
                chain_breaks.append(two in {"&&", "||"})
                i += 2
                continue
            if ch in {";", "&", "\n"}:
                pieces.append("".join(current))
                current = []
                chain_breaks.append(True)
                i += 1
                continue
            if ch == "|":
                pieces.append("".join(current))
                current = []
                chain_breaks.append(False)
                i += 1
                continue
        current.append(ch)
        i += 1
    pieces.append("".join(current))

    chains: list[list[str]] = []
    pipe: list[str] = []
    for idx, piece in enumerate(pieces):
        stripped = piece.strip()
        if stripped:
            pipe.append(stripped)
        if idx == len(pieces) - 1:
            continue
        if chain_breaks[idx]:
            if pipe:
                chains.append(pipe)
            pipe = []
    if pipe:
        chains.append(pipe)
    del text
    return chains


@dataclass(frozen=True)
class StaticCheckHit:
    """静态检查命中：类名 + 触发段。"""

    category: str
    segment: str


class StaticChecker:
    """8 类形态学检查器：任一段命中即 DENY（独立于白名单与两旋钮）。

    workspace_roots 为可写根（已规范化的正斜杠小写路径元组）；
    默认空 = 一切绝对路径目标都视为根外（fail-closed）。
    """

    def __init__(
        self,
        allowed_domains: frozenset[str] | None = None,
        workspace_roots: tuple[str, ...] = (),
        allow_localhost: bool = True,
    ) -> None:
        self._domains = (
            allowed_domains if allowed_domains is not None else _DEFAULT_ALLOWED_DOMAINS
        )
        self._workspace_roots = workspace_roots
        self._allow_localhost = allow_localhost

    def check(self, command: str) -> Decision | None:
        """整条命令检查：命中返回 deny Decision；解析失败返回 ask；干净返回 None。"""
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
        chains = _operator_chains(command)
        downloader_segments = self._downloader_segments(chains)
        for seg in segments:
            hit = self._check_segment(seg, downloader_segments)
            if hit is not None:
                return Decision(
                    action=DecisionAction.DENY,
                    rule_id=f"static.{hit.category}",
                    reason=f"命中静态正则检查器 {hit.category} 类（形态学危险，全档拦截）",
                    command=command,
                    segment=hit.segment,
                )
        return None

    def _check_segment(
        self, seg: Segment, downloader_segments: frozenset[str]
    ) -> StaticCheckHit | None:
        for category in _CHECK_FUNCS:
            name = category.__name__
            if name == "download_exec":
                if seg.text in downloader_segments:
                    return StaticCheckHit(name, seg.text)
                continue
            if category(self, seg):
                return StaticCheckHit(name, seg.text)
        return None

    def _downloader_segments(self, chains: list[list[str]]) -> frozenset[str]:
        """管道链中"下载器段 → 更后解释器段"的下载器段文本集合。"""
        hits: set[str] = set()
        for pipe in chains:
            programs = [program_of(s) for s in pipe]
            for i, prog in enumerate(programs):
                if prog.lower() not in _DOWNLOADERS:
                    continue
                if any(later.lower() in _INTERPRETERS for later in programs[i + 1 :]):
                    hits.add(pipe[i])
        return frozenset(hits)


# ---- 8 类检查函数（判定顺序即注册顺序；self 为 StaticChecker 实例）----

def catastrophic_delete(self: StaticChecker, seg: Segment) -> bool:
    prog = seg.program.lower()
    if prog not in _DELETE_PROGRAMS:
        # 解释器内联脚本（bash -c 'rm -rf ~' / node -e "rm -rf /"）：
        # 段首程序不是删除器，但内联体含删除形态时同样按类 1 判
        return _inline_catastrophic(seg.text)
    stripped = strip_wrappers(seg.text)
    parts = stripped.split(None, 1)
    rest_text = parts[1] if len(parts) > 1 else ""
    if not _RECURSIVE_FLAG_RE.search(rest_text):
        return False
    # / 开头 token 仅对 Windows 删除程序视为 flag（/s /q）；POSIX rm 的 / 是路径
    windows_flags = prog in _WINDOWS_DELETE_PROGRAMS
    for tok in _tokenize(rest_text):
        if tok.startswith("-"):
            continue
        if windows_flags and re.match(r"^/[A-Za-z]$", tok):
            continue
        if _is_critical_target(tok, self._workspace_roots):
            return True
    return False


def _inline_catastrophic(segment_text: str) -> bool:
    """解释器 -c/-e/-Command 内联脚本体内含 rm/rmdir/…+递归 flag 形态。"""
    for m in _INLINE_DELETE_RE.finditer(segment_text):
        body = m.group(1).strip("'\"")
        if _INLINE_RM_RE.search(body):
            return True
    return False


def download_exec(self: StaticChecker, seg: Segment) -> bool:
    # 管道链结构在 check() 统一判定（_downloader_segments），此处不独立判
    return False


def privilege_escalation(self: StaticChecker, seg: Segment) -> bool:
    return bool(_PRIV_PREFIX_RE.match(strip_wrappers(seg.text)))


def credentials(self: StaticChecker, seg: Segment) -> bool:
    return bool(_SENSITIVE_PATH_RE.search(seg.text))


def git_irreversible(self: StaticChecker, seg: Segment) -> bool:
    return any(p.search(seg.text) for p in _GIT_IRREVERSIBLE_PATTERNS)


def network_egress(self: StaticChecker, seg: Segment) -> bool:
    for host in _extract_hosts(seg.text):
        lowered = host.lower()
        if self._allow_localhost and lowered in _LOCAL_HOSTS:
            continue
        if not _domain_allowed(lowered, self._domains):
            return True
    return False


def redirect(self: StaticChecker, seg: Segment) -> bool:
    for m in _REDIRECT_TOKEN_RE.finditer(seg.text):
        tok = _first_token(seg.text[m.end() :])
        if tok is None:
            return False
        if _PROTECTED_REDIRECT_RE.search(tok):
            return True
        if _is_outside_writable(tok, self._workspace_roots):
            return True
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
    """粗粒度 token 化（形态学判定够用；引号内空格不进一步拆）。"""
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
    parts = stripped.split(None, 1)
    return parts[0]


def _is_critical_target(tok: str, roots: tuple[str, ...]) -> bool:
    """关键目标：~、..、裸 *、$ 形态、token 首 /、盘根、UNC、首反斜杠、根外绝对路径。"""
    body = tok.strip("'\"")
    if not body:
        return False
    if body == "~" or body.startswith("~/"):
        return True
    if body == ".." or body.startswith("../") or body.startswith("..\\"):
        return True
    if body == "*" or body.startswith("/*") or body.endswith("/*"):
        return True
    if "$" in body:
        return True
    if body.startswith("/"):
        return not _within_roots(body, roots)
    if _UNC_RE.match(body):
        return True
    if _WINDOWS_DRIVE_RE.match(body):
        return not _within_roots(body, roots)
    if body.startswith("\\"):
        return True
    return False


def _normalized(body: str) -> str:
    return body.replace("\\", "/").casefold().rstrip("/")


def _within_roots(body: str, roots: tuple[str, ...]) -> bool:
    norm = _normalized(body)
    for root in roots:
        r = root.rstrip("/")
        if norm == r or norm.startswith(r + "/"):
            return True
    return False


def _extract_hosts(segment_text: str) -> list[str]:
    hosts = [m.group(1) for m in _URL_RE.finditer(segment_text)]
    hosts += [m.group(1) for m in _SCP_RE.finditer(segment_text)]
    return hosts


def _domain_allowed(host: str, domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _is_outside_writable(tok: str, roots: tuple[str, ...]) -> bool:
    """重定向目标绝对路径是否在可写根外（~ 前缀 token 视为根外）。"""
    body = tok.strip("'\"")
    if body.startswith("~"):
        return True
    if not (
        body.startswith("/") or _WINDOWS_DRIVE_RE.match(body) or _UNC_RE.match(body)
    ):
        return False
    if _normalized(body) in {"/dev/null", "nul"}:
        return False
    return not _within_roots(body, roots)


__all__ = [
    "ParseError",
    "Segment",
    "StaticChecker",
    "parse_command",
    "program_of",
    "strip_wrappers",
]
