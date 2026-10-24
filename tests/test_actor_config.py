"""derive_actor_config 纯函数（05 票终裁 7，验收 5）：8 配置表驱动。

way∈{way1..way4} 否则默认 way1；guidance_enabled=mode∈{auto,ask}；
派生结果仅用于 actor 身体选择，不持久化不写 state。
"""

from __future__ import annotations

import pytest

from project_agent.routing import derive_actor_config

# 8 配置（4 方式 × 2 指引）派生表
DERIVE_TABLE = [
    ("way1", "auto", {"build_way": "way1", "guidance_enabled": True}),
    ("way1", "ask", {"build_way": "way1", "guidance_enabled": True}),
    ("way1", "off", {"build_way": "way1", "guidance_enabled": False}),
    ("way2", "auto", {"build_way": "way2", "guidance_enabled": True}),
    ("way2", "off", {"build_way": "way2", "guidance_enabled": False}),
    ("way3", "ask", {"build_way": "way3", "guidance_enabled": True}),
    ("way4", "off", {"build_way": "way4", "guidance_enabled": False}),
    ("way4", "ask", {"build_way": "way4", "guidance_enabled": True}),
]


@pytest.mark.parametrize(
    ("way", "mode", "expected"),
    DERIVE_TABLE,
    ids=[f"{w}-{m}" for w, m, _ in DERIVE_TABLE],
)
def test_derive_actor_config_table(way, mode, expected):
    assert derive_actor_config(way, mode) == expected


@pytest.mark.parametrize(
    ("way", "mode", "expected_way"),
    [
        ("way9", "auto", "way1"),  # 未知 way → 默认 way1
        ("", "off", "way1"),
        (None, "off", "way1"),
    ],
    ids=["unknown-way", "empty-way", "none-way"],
)
def test_derive_actor_config_unknown_way_defaults_way1(way, mode, expected_way):
    cfg = derive_actor_config(way, mode)
    assert cfg["build_way"] == expected_way
    assert cfg["guidance_enabled"] == (mode in ("auto", "ask"))


@pytest.mark.parametrize(
    "mode",
    ["auto", "ask", "off", None, "", "yolo"],
    ids=["auto", "ask", "off", "none", "empty", "unknown"],
)
def test_derive_actor_config_guidance_enabled_membership(mode):
    cfg = derive_actor_config("way1", mode)
    assert cfg["guidance_enabled"] == (mode in ("auto", "ask"))
    assert isinstance(cfg["guidance_enabled"], bool)


def test_derive_actor_config_keys_closed():
    cfg = derive_actor_config("way1", "auto")
    assert set(cfg) == {"build_way", "guidance_enabled"}
