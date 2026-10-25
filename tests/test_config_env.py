""".env 配置格式：解析/渲染/迁移/BOM 容错。"""

from __future__ import annotations

import json

from project_agent.config import AppConfig, ConfigStore, parse_env, render_env


def test_parse_env_basic_and_quoting():
    text = "main_model=deepseek-chat\napi_key=sk-x\n\n# 注释行\nbase_url='api.deepseek.com'\nsub_model=\"deepseek-reasoner\"\n"
    values = parse_env(text)
    assert values == {
        "main_model": "deepseek-chat",
        "api_key": "sk-x",
        "base_url": "api.deepseek.com",
        "sub_model": "deepseek-reasoner",
    }


def test_parse_env_bom_and_junk_lines():
    # UTF-8 BOM 前缀 + 无 = 行 + 空值
    text = "\ufeffmain_model=deepseek-chat\napi_key=\n不是配置行\n"
    values = parse_env(text)
    assert values["main_model"] == "deepseek-chat"
    assert values["api_key"] == ""


def test_render_env_roundtrip():
    config = AppConfig(
        main_model="deepseek-chat", api_key="sk-x", base_url="b", sub_model="s"
    )
    text = render_env(config)
    assert parse_env(text) == {
        "main_model": "deepseek-chat",
        "api_key": "sk-x",
        "base_url": "b",
        "sub_model": "s",
        "decision_mode": "ai_review",  # 14 票新增字段（默认值也落盘）
    }


def test_render_env_includes_manual_decision_mode():
    config = AppConfig(
        main_model="deepseek-chat", api_key="sk-x", decision_mode="manual"
    )
    assert parse_env(render_env(config))["decision_mode"] == "manual"


def test_store_load_invalid_decision_mode_defaults_to_ai_review(tmp_path):
    """受控归一：非法 decision_mode → ai_review（14 票默认）。"""
    path = tmp_path / "config.env"
    path.write_text(
        "main_model=deepseek-chat\napi_key=sk-x\ndecision_mode=banana\n",
        encoding="utf-8",
    )
    assert ConfigStore(path).load() == AppConfig(
        main_model="deepseek-chat", api_key="sk-x", decision_mode="ai_review"
    )


def test_store_save_load_roundtrip(tmp_path):
    store = ConfigStore(tmp_path / "config.env")
    store.save(
        AppConfig(main_model="deepseek-chat", api_key="sk-x", base_url="", sub_model="")
    )
    loaded = store.load()
    assert loaded == AppConfig(
        main_model="deepseek-chat", api_key="sk-x", base_url="", sub_model=""
    )


def test_store_load_missing_returns_none(tmp_path):
    assert ConfigStore(tmp_path / "config.env").load() is None


def test_store_load_incomplete_env_returns_none(tmp_path):
    """必填缺失（无 api_key）→ None：视同无配置，问卷重建。"""
    path = tmp_path / "config.env"
    path.write_text("main_model=deepseek-chat\n", encoding="utf-8")
    assert ConfigStore(path).load() is None


def test_store_migrates_legacy_json(tmp_path):
    """旧 config.json 首读自动迁移：读 json → 写 .env → 删 json。"""
    legacy = tmp_path / "config.json"
    legacy.write_text(
        json.dumps(
            {
                "main_model": "deepseek-chat",
                "api_key": "sk-old",
                "base_url": "api.deepseek.com",
                "sub_model": "",
            }
        ),
        encoding="utf-8",
    )
    store = ConfigStore(tmp_path / "config.env")
    loaded = store.load()
    assert loaded == AppConfig(
        main_model="deepseek-chat", api_key="sk-old", base_url="api.deepseek.com", sub_model=""
    )
    assert not legacy.exists()  # 旧文件删除
    assert (tmp_path / "config.env").exists()
    # 二次读走 .env 直路（迁移一次性）
    assert store.load() == loaded
