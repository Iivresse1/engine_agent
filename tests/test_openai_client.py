"""真模型客户端协议面（零网络：chat 桩注入）+ base_url 归一。"""

from __future__ import annotations

from typing import Any

from project_agent.model_client import ModelResult, ModelUsage
from project_agent.openai_client import OpenAICompatClient, normalize_base_url


class _StubChat:
    """chat 桩：记录 invoke 消息，回放预设响应（AIMessage 鸭子形）。"""

    def __init__(self, text: str, usage: dict[str, int] | None = None) -> None:
        self._text = text
        self._usage = usage
        self.invoked: list[list[dict[str, Any]]] = []

    def invoke(self, messages: list[dict[str, Any]]) -> Any:
        self.invoked.append(messages)

        class _Msg:
            pass

        msg = _Msg()
        msg.content = self._text  # type: ignore[attr-defined]
        if self._usage is not None:
            msg.usage_metadata = self._usage  # type: ignore[attr-defined]
        return msg


def test_normalize_base_url_variants():
    assert normalize_base_url("") is None
    assert normalize_base_url("   ") is None
    # 缺 scheme 补 https://
    assert normalize_base_url("api.deepseek.com") == "https://api.deepseek.com"
    assert normalize_base_url("api.deepseek.com/") == "https://api.deepseek.com"
    # 已带 scheme 原样（仅去尾斜杠）
    assert normalize_base_url("https://api.deepseek.com/") == "https://api.deepseek.com"
    assert normalize_base_url("http://localhost:8000") == "http://localhost:8000"


def test_complete_passes_messages_and_reads_text_and_usage():
    chat = _StubChat("答案", {"input_tokens": 7, "output_tokens": 3})
    client = OpenAICompatClient("deepseek-chat", "sk-x", "api.deepseek.com", chat=chat)
    result = client.complete(
        [{"role": "user", "content": "问"}], role="actor", thread_id="t1"
    )
    assert isinstance(result, ModelResult)
    assert result.text == "答案"
    assert result.usage == ModelUsage(input_tokens=7, output_tokens=3)
    # 消息字典直喂（OpenAI 形）
    assert chat.invoked == [[{"role": "user", "content": "问"}]]


def test_complete_reads_response_metadata_fallback():
    """usage_metadata 缺 → response_metadata.token_usage（openai 原始字段名）。"""

    class _Msg:
        content = "回"

    _Msg.response_metadata = {"token_usage": {"prompt_tokens": 11, "completion_tokens": 4}}  # type: ignore[attr-defined]

    class _Chat:
        def invoke(self, messages: list[dict[str, Any]]) -> Any:
            return _Msg()

    client = OpenAICompatClient("m", "k", "", chat=_Chat())
    result = client.complete([{"role": "user", "content": "q"}], role="r", thread_id="t")
    assert result.usage == ModelUsage(input_tokens=11, output_tokens=4)


def test_complete_usage_none_when_both_missing():
    class _Msg:
        content = "回"

    class _Chat:
        def invoke(self, messages: list[dict[str, Any]]) -> Any:
            return _Msg()

    client = OpenAICompatClient("m", "k", "", chat=_Chat())
    result = client.complete([{"role": "user", "content": "q"}], role="r", thread_id="t")
    assert result.usage is None


def test_lazy_import_no_network_on_module_load():
    """模块导入零网络零重依赖（langchain_openai 惰性导入进 _default_chat）。"""
    import subprocess
    import sys

    code = (
        "import sys; "
        "sys.modules['langchain_openai'] = None; "  # 装作不可用
        "import project_agent.openai_client as m; "
        "assert 'langchain_openai' not in sys.modules or sys.modules['langchain_openai'] is None; "
        "print('ok')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout
