"""11 票切片 1：REPL 混合路由三层纯函数（验收 3/4 表驱动）。

层序钉板：
1) 显式斜杠优先（零 LLM）
2) 报错特征规则预筛（Traceback/Error: 特征 **且** demo 阶段活跃）
3) LLM 窄分类兜底（只判"报错回传 vs 普通输入"，二分；默认 normal）
"""

from __future__ import annotations

import pytest

from project_agent.hybrid_router import route_input
from tests.doubles.fake_model import ScriptedModel

BUILDING = {"demo_phase": "building"}


# —— 层 1：斜杠优先（零 LLM，压过一切） ——


def test_slash_wins_over_everything():
    classifier = ScriptedModel(["这是报错回传"])
    assert route_input("/status", last_state=BUILDING, error_classifier=classifier) == "slash"
    assert (
        route_input(
            "/help " + "Traceback (most recent call last)", last_state=BUILDING
        )
        == "slash"
    )
    assert classifier.calls == []  # 零 LLM


# —— 层 2：报错特征预筛需 demo 阶段活跃 ——


@pytest.mark.parametrize(
    "text",
    [
        "Traceback (most recent call last):\n  File \"x.py\", line 1",
        "  Error: 端口被占用",
        "Error：依赖缺失",
        "SyntaxError: invalid syntax",
        "ModuleNotFoundError: No module named 'flask'",
        "ZeroDivisionError: division by zero",
    ],
    ids=["traceback", "indented-error", "fullwidth-colon", "syntax", "module", "zero"],
)
def test_error_feature_prefilter_requires_demo_active(text):
    assert route_input(text, last_state=BUILDING) == "error_return"
    # demo 阶段不活跃：特征不触发，回落 normal（无分类器）
    assert route_input(text, last_state={}) == "normal"
    assert route_input(text, last_state={"demo_phase": "skipped"}) == "normal"


def test_error_feature_prefilter_is_zero_llm():
    """特征命中即返回，分类器零调用（预筛在窄分类之前）。"""
    classifier = ScriptedModel(["普通输入"])
    assert route_input("ZeroDivisionError: x", last_state=BUILDING, error_classifier=classifier) == "error_return"
    assert classifier.calls == []


def test_ordinary_text_with_demo_active_falls_through_to_default_normal():
    assert route_input("继续改一下按钮颜色", last_state=BUILDING) == "normal"


# —— 层 3：LLM 窄分类兜底（二分；默认为 normal） ——


def test_classifier_binary_error_branch():
    classifier = ScriptedModel(["用户粘贴的是报错信息"])
    result = route_input("跑起来就挂了", last_state=BUILDING, error_classifier=classifier)
    assert result == "error_return"
    call = classifier.calls[0]
    assert call["role"] == "router"
    assert call["messages"] == [{"role": "user", "content": "跑起来就挂了"}]
    assert call["thread_id"] == ""


def test_classifier_binary_normal_branch():
    classifier = ScriptedModel(["普通输入，继续推进"])
    assert route_input("把标题改成蓝色", last_state=BUILDING, error_classifier=classifier) == "normal"


def test_classifier_none_defaults_to_normal():
    assert route_input("把标题改成蓝色", last_state=BUILDING, error_classifier=None) == "normal"
