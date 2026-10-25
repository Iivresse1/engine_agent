"""gui_config 纯函数层（零 GUI）：表单校验 + 测试连接（MockTransport 注入）。"""

from __future__ import annotations

import httpx

from project_agent.config import AppConfig
from project_agent.gui_config import form_fields_to_config
from project_agent.gui_config import test_connection as ping_connection


def test_form_fields_to_config_full():
    config = form_fields_to_config(
        {
            "main_model": "deepseek-chat",
            "api_key": "sk-x",
            "base_url": "api.deepseek.com",
            "sub_model": "deepseek-reasoner",
            "decision_mode": "manual",
        }
    )
    assert config == AppConfig(
        main_model="deepseek-chat",
        api_key="sk-x",
        base_url="api.deepseek.com",
        sub_model="deepseek-reasoner",
        decision_mode="manual",
    )


def test_form_fields_to_config_defaults():
    config = form_fields_to_config({"main_model": "m", "api_key": "k"})
    assert config is not None
    assert config.base_url == ""
    assert config.sub_model == ""
    assert config.decision_mode == "ai_review"  # 默认开


def test_form_fields_to_config_missing_required_returns_none():
    assert form_fields_to_config({"api_key": "k"}) is None
    assert form_fields_to_config({"main_model": "m"}) is None
    assert form_fields_to_config({}) is None


def test_form_fields_to_config_strips_whitespace():
    config = form_fields_to_config({"main_model": " m ", "api_key": " k "})
    assert config.main_model == "m"
    assert config.api_key == "k"


def test_form_fields_to_config_decision_mode_normalizes():
    """非 "manual" 一律归 ai_review（GUI 开关两态的容错）。"""
    config = form_fields_to_config(
        {"main_model": "m", "api_key": "k", "decision_mode": "bogus"}
    )
    assert config.decision_mode == "ai_review"
    config2 = form_fields_to_config(
        {"main_model": "m", "api_key": "k", "decision_mode": ""}
    )
    assert config2.decision_mode == "ai_review"


# ---------- test_connection（httpx.MockTransport 零网络） ----------


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"choices": []})


def _unauthorized_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": "bad key"})


def _refused_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused")


def test_connection_ok_with_scheme():
    ok, message = ping_connection(
        "deepseek-chat", "sk-x", "https://api.deepseek.com", transport=httpx.MockTransport(_ok_handler)
    )
    assert ok is True
    assert "HTTP 200" in message


def test_connection_ok_schemeless_base_url():
    """缺 scheme 的 base_url（api.deepseek.com）归一后可达。"""
    ok, _ = ping_connection(
        "deepseek-chat", "sk-x", "api.deepseek.com", transport=httpx.MockTransport(_ok_handler)
    )
    assert ok is True


def test_connection_empty_base_uses_openai_default():
    """空 base_url → 官方默认端点（请求路径断言）。"""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={})

    ok, _ = ping_connection("gpt-4o", "sk-x", "", transport=httpx.MockTransport(handler))
    assert ok is True
    assert seen["url"].startswith("https://api.openai.com/v1/chat/completions")


def test_connection_http_error_reports_code():
    ok, message = ping_connection(
        "m", "bad-key", "https://api.deepseek.com",
        transport=httpx.MockTransport(_unauthorized_handler),
    )
    assert ok is False
    assert "HTTP 401" in message


def test_connection_network_error_reports_failure():
    ok, message = ping_connection(
        "m", "k", "https://example.invalid",
        transport=httpx.MockTransport(_refused_handler),
    )
    assert ok is False
    assert "ConnectError" in message or "连接失败" in message


def test_connection_sends_bearer_and_1token_body():
    """请求形状：Bearer 头 + max_tokens=1 + ping 消息。"""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        import json as _json

        seen["body"] = _json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={})

    ping_connection("m", "sk-9", "https://api.deepseek.com", transport=httpx.MockTransport(handler))
    assert seen["auth"] == "Bearer sk-9"
    body = seen["body"]
    assert body["model"] == "m"
    assert body["max_tokens"] == 1
    assert body["messages"][0]["content"] == "ping"


def test_collect_config_gui_fails_closed_without_display(monkeypatch):
    """无 tkinter（ImportError）→ None（CLI 退终端问卷）。"""
    import builtins

    real_import = builtins.__import__

    def _no_tkinter(name, *args, **kwargs):
        if name == "tkinter":
            raise ImportError("no tkinter")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_tkinter)
    from project_agent.gui_config import collect_config_gui

    assert collect_config_gui() is None
