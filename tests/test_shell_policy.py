"""ShellPolicy 判定管线：拆段逐段判、剥壳、解析失败 fail-closed、白名单序、两旋钮矩阵。"""

from __future__ import annotations

import pytest

from project_agent.tools.decision import DecisionAction
from project_agent.tools.knobs import Boundary, Interrupt, ShellKnobs
from project_agent.tools.shell_policy import ShellPolicy, WhitelistRules

WORKSPACE = "D:/ws/project"


def _knobs(
    boundary: Boundary = Boundary.PROJECT_WRITE, interrupt: Interrupt = Interrupt.AI_REVIEW
) -> ShellKnobs:
    flags = {}
    if boundary is Boundary.FULL:
        flags["full_via_flag"] = True
    if interrupt is Interrupt.YOLO:
        flags["yolo_via_flag"] = True
    return ShellKnobs(boundary=boundary, interrupt=interrupt, **flags)


def _policy(
    boundary: Boundary = Boundary.PROJECT_WRITE,
    interrupt: Interrupt = Interrupt.AI_REVIEW,
    rules: WhitelistRules | None = None,
) -> ShellPolicy:
    return ShellPolicy(knobs=_knobs(boundary, interrupt), workspace_root=WORKSPACE, rules=rules)


# ---- 拆段逐段判 ----

def test_compound_deny_carries_segment():
    policy = _policy()
    decision = policy.check("git status && rm -rf /")
    assert decision.action is DecisionAction.DENY
    assert decision.rule_id == "static.catastrophic_delete"
    assert decision.segment == "rm -rf /"


def test_compound_all_allow():
    policy = _policy()
    decision = policy.check("npm install && npm run build")
    assert decision.action is DecisionAction.ALLOW
    assert decision.rule_id == "whitelist.allow_write"


def test_compound_unknown_tail_segment_wins_as_ask():
    policy = _policy()
    decision = policy.check("ls && docker run x")
    assert decision.action is DecisionAction.ASK
    assert decision.segment == "docker run x"


def test_subshell_segments_judged():
    policy = _policy()
    decision = policy.check("(cd a && cd b)")
    assert decision.action is DecisionAction.ALLOW


def test_pipe_segments_judged():
    policy = _policy()
    decision = policy.check("git status | wc")
    assert decision.action is DecisionAction.ALLOW


# ---- 剥壳 ----

def test_wrapper_timeout_stripped():
    policy = _policy()
    decision = policy.check("timeout 30 npm install")
    assert decision.action is DecisionAction.ALLOW


def test_env_assignment_deny_sees_through():
    policy = _policy()
    decision = policy.check("FOO=bar rm -rf /")
    assert decision.action is DecisionAction.DENY
    assert decision.rule_id == "static.catastrophic_delete"


def test_wrapper_nice_stripped():
    policy = _policy()
    decision = policy.check("nice -n 10 git status")
    assert decision.action is DecisionAction.ALLOW


# ---- 解析失败 = ask（fail-closed）----

@pytest.mark.parametrize(
    "command",
    ["npm test &&", 'echo "unclosed', "(cd a && cd b"],
    ids=["dangling-op", "unclosed-quote", "unclosed-paren"],
)
def test_parse_failure_is_ask(command: str):
    policy = _policy()
    decision = policy.check(command)
    assert decision.action is DecisionAction.ASK
    assert decision.rule_id == "parse.failure"


# ---- 白名单序 deny > ask > allow ----

def test_whitelist_deny_beats_allow():
    # git commit --amend 同时命中 deny(--amend 草案) 与 allow(git commit *) → deny
    rules = WhitelistRules(
        allow_read=("git status",),
        allow_write=("git commit *",),
        ask=("git push *",),
        deny=("git commit --amend*",),
    )
    policy = _policy(rules=rules)
    decision = policy.check("git commit --amend -m x")
    assert decision.action is DecisionAction.DENY
    assert decision.rule_id == "static.git_irreversible"


def test_whitelist_ask_beats_allow():
    rules = WhitelistRules(
        allow_read=("ls *",),
        allow_write=("npm install *",),
        ask=("npm install *",),
    )
    policy = _policy(rules=rules)
    decision = policy.check("npm install lodash")
    assert decision.action is DecisionAction.ASK
    assert decision.rule_id == "whitelist.ask"


def test_default_rules_git_clone_is_ask():
    policy = _policy()
    decision = policy.check("git clone https://github.com/user/repo.git")
    assert decision.action is DecisionAction.ASK
    assert decision.rule_id == "whitelist.ask"


def test_default_rules_git_push_is_ask():
    policy = _policy()
    decision = policy.check("git push origin main")
    assert decision.action is DecisionAction.ASK


def test_tail_star_matches_bare_command():
    policy = _policy()
    assert policy.check("ls").action is DecisionAction.ALLOW
    assert policy.check("pwd").action is DecisionAction.ALLOW


# ---- 3×3 两旋钮矩阵 ----

MATRIX_CASES = [
    # (命令, boundary, interrupt, 期望 action, 期望 rule_id)
    ("ls -la", Boundary.READONLY, Interrupt.AI_REVIEW, "allow", "whitelist.allow_read"),
    ("mkdir demo", Boundary.READONLY, Interrupt.AI_REVIEW, "deny", "boundary.readonly"),
    ("mkdir C:\\Windows\\pwn", Boundary.READONLY, Interrupt.AI_REVIEW, "deny", "boundary.readonly"),
    ("docker run x", Boundary.READONLY, Interrupt.AI_REVIEW, "ask", "whitelist.miss"),
    ("rm -rf /", Boundary.READONLY, Interrupt.AI_REVIEW, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.READONLY, Interrupt.AI_REVIEW, "ask", "whitelist.ask"),

    ("ls -la", Boundary.PROJECT_WRITE, Interrupt.AI_REVIEW, "allow", "whitelist.allow_read"),
    ("mkdir demo", Boundary.PROJECT_WRITE, Interrupt.AI_REVIEW, "allow", "whitelist.allow_write"),
    ("mkdir C:\\Windows\\pwn", Boundary.PROJECT_WRITE, Interrupt.AI_REVIEW, "deny", "boundary.outside_workspace"),
    ("docker run x", Boundary.PROJECT_WRITE, Interrupt.AI_REVIEW, "ask", "whitelist.miss"),
    ("rm -rf /", Boundary.PROJECT_WRITE, Interrupt.AI_REVIEW, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.PROJECT_WRITE, Interrupt.AI_REVIEW, "ask", "whitelist.ask"),

    ("ls -la", Boundary.FULL, Interrupt.AI_REVIEW, "allow", "whitelist.allow_read"),
    ("mkdir demo", Boundary.FULL, Interrupt.AI_REVIEW, "allow", "whitelist.allow_write"),
    ("mkdir C:\\Windows\\pwn", Boundary.FULL, Interrupt.AI_REVIEW, "allow", "whitelist.allow_write"),
    ("docker run x", Boundary.FULL, Interrupt.AI_REVIEW, "ask", "whitelist.miss"),
    ("rm -rf /", Boundary.FULL, Interrupt.AI_REVIEW, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.FULL, Interrupt.AI_REVIEW, "ask", "whitelist.ask"),

    ("ls -la", Boundary.READONLY, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("mkdir demo", Boundary.READONLY, Interrupt.HUMAN, "deny", "boundary.readonly"),
    ("mkdir C:\\Windows\\pwn", Boundary.READONLY, Interrupt.HUMAN, "deny", "boundary.readonly"),
    ("docker run x", Boundary.READONLY, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("rm -rf /", Boundary.READONLY, Interrupt.HUMAN, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.READONLY, Interrupt.HUMAN, "ask", "interrupt.human"),

    ("ls -la", Boundary.PROJECT_WRITE, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("mkdir demo", Boundary.PROJECT_WRITE, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("mkdir C:\\Windows\\pwn", Boundary.PROJECT_WRITE, Interrupt.HUMAN, "deny", "boundary.outside_workspace"),
    ("docker run x", Boundary.PROJECT_WRITE, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("rm -rf /", Boundary.PROJECT_WRITE, Interrupt.HUMAN, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.PROJECT_WRITE, Interrupt.HUMAN, "ask", "interrupt.human"),

    ("ls -la", Boundary.FULL, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("mkdir demo", Boundary.FULL, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("mkdir C:\\Windows\\pwn", Boundary.FULL, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("docker run x", Boundary.FULL, Interrupt.HUMAN, "ask", "interrupt.human"),
    ("rm -rf /", Boundary.FULL, Interrupt.HUMAN, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.FULL, Interrupt.HUMAN, "ask", "interrupt.human"),

    ("ls -la", Boundary.READONLY, Interrupt.YOLO, "allow", "whitelist.allow_read"),
    ("mkdir demo", Boundary.READONLY, Interrupt.YOLO, "deny", "boundary.readonly"),
    ("mkdir C:\\Windows\\pwn", Boundary.READONLY, Interrupt.YOLO, "deny", "boundary.readonly"),
    ("docker run x", Boundary.READONLY, Interrupt.YOLO, "allow", "interrupt.yolo"),
    ("rm -rf /", Boundary.READONLY, Interrupt.YOLO, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.READONLY, Interrupt.YOLO, "allow", "interrupt.yolo"),

    ("ls -la", Boundary.PROJECT_WRITE, Interrupt.YOLO, "allow", "whitelist.allow_read"),
    ("mkdir demo", Boundary.PROJECT_WRITE, Interrupt.YOLO, "allow", "whitelist.allow_write"),
    ("mkdir C:\\Windows\\pwn", Boundary.PROJECT_WRITE, Interrupt.YOLO, "deny", "boundary.outside_workspace"),
    ("docker run x", Boundary.PROJECT_WRITE, Interrupt.YOLO, "allow", "interrupt.yolo"),
    ("rm -rf /", Boundary.PROJECT_WRITE, Interrupt.YOLO, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.PROJECT_WRITE, Interrupt.YOLO, "allow", "interrupt.yolo"),

    ("ls -la", Boundary.FULL, Interrupt.YOLO, "allow", "whitelist.allow_read"),
    ("mkdir demo", Boundary.FULL, Interrupt.YOLO, "allow", "whitelist.allow_write"),
    ("mkdir C:\\Windows\\pwn", Boundary.FULL, Interrupt.YOLO, "allow", "whitelist.allow_write"),
    ("docker run x", Boundary.FULL, Interrupt.YOLO, "allow", "interrupt.yolo"),
    ("rm -rf /", Boundary.FULL, Interrupt.YOLO, "deny", "static.catastrophic_delete"),
    ("git push origin main", Boundary.FULL, Interrupt.YOLO, "allow", "interrupt.yolo"),
]


@pytest.mark.parametrize(
    ("command", "boundary", "interrupt", "expected_action", "expected_rule"),
    MATRIX_CASES,
    ids=[
        f"{c[:12]}|{b.value}|{i.value}"
        for c, b, i, _, _ in MATRIX_CASES
    ],
)
def test_two_knob_matrix(command, boundary, interrupt, expected_action, expected_rule):
    policy = _policy(boundary=boundary, interrupt=interrupt)
    decision = policy.check(command)
    assert decision.action.value == expected_action, (
        f"{command} @ {boundary}/{interrupt}: {decision.rule_id} {decision.reason}"
    )
    assert decision.rule_id == expected_rule, (
        f"{command} @ {boundary}/{interrupt}: {decision.action} {decision.reason}"
    )


# ---- Decision 完整性 ----

def test_decision_carries_all_fields():
    policy = _policy()
    decision = policy.check("git status && rm -rf /")
    assert decision.command == "git status && rm -rf /"
    assert decision.segment == "rm -rf /"
    assert decision.reason
    assert decision.rule_id == "static.catastrophic_delete"


def test_default_rules_allow_read_section():
    policy = _policy(boundary=Boundary.READONLY)
    for command in ("ls -la", "cat README.md", "git status", "git log -3", "pwd"):
        decision = policy.check(command)
        assert decision.action is DecisionAction.ALLOW, command


def test_tmp_dir_is_writable_root():
    # tempfile 根也是可写根：重定向进 temp 不触发 outside_workspace
    policy = _policy()
    decision = policy.check("npm install > log.txt")
    assert decision.action is DecisionAction.ALLOW
