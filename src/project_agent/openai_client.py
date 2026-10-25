"""真模型客户端：OpenAI 兼容端点（DeepSeek 等）→ ModelClient 协议薄适配。

v1.5 接线票：cli.py 从 config.env 读模型/key/base_url 构造本客户端，
MeteredModel 包装后传入 build_graph —— model 非 None 分支（graph.py）
闭合 verifier 环；cheap_model 非 None 挂上压缩横切四节点。

base_url 容错：用户手填常缺 scheme（如 api.deepseek.com）——构造期
归一补 https://（normalize_base_url 纯函数，缺 scheme 不修正则
openai 客户端把整串当 host 报错）。

langchain_openai 为惰性导入：模块导入零网络零重依赖，测试注入桩
（chat 参数）时无需安装包本体即跑协议面。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from project_agent.model_client import ModelResult, ModelUsage

_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


def normalize_base_url(base_url: str) -> str | None:
    """空 → None（openai SDK 官方默认端点）；缺 scheme 补 https://；去尾斜杠。"""
    url = (base_url or "").strip()
    if not url:
        return None
    if not _SCHEME.match(url):
        url = f"https://{url}"
    return url.rstrip("/")


def _default_chat(model: str, api_key: str, base_url: str) -> Any:
    """生产路径：ChatOpenAI 打 OpenAI 兼容端点（DeepSeek/官方皆可）。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=normalize_base_url(base_url),
        max_retries=2,
    )


def _response_text(response: Any) -> str:
    """AIMessage 文本：优先 .text（langchain-core 1.x），退 .content。"""
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(response, "content", None)
    return content if isinstance(content, str) else str(content)


def _response_usage(response: Any) -> ModelUsage | None:
    """usage_metadata（input/output_tokens）优先；退 response_metadata
    的 token_usage（prompt/completion_tokens——openai 原始字段名）；
    两者皆缺 → None（MeteredModel 对 None 不入账）。"""
    meta = getattr(response, "usage_metadata", None)
    if isinstance(meta, Mapping):
        try:
            return ModelUsage(
                input_tokens=int(meta["input_tokens"]),
                output_tokens=int(meta["output_tokens"]),
            )
        except (KeyError, TypeError, ValueError):
            pass
    raw = getattr(response, "response_metadata", None)
    token_usage = raw.get("token_usage") if isinstance(raw, Mapping) else None
    if isinstance(token_usage, Mapping):
        try:
            return ModelUsage(
                input_tokens=int(token_usage["prompt_tokens"]),
                output_tokens=int(token_usage["completion_tokens"]),
            )
        except (KeyError, TypeError, ValueError):
            pass
    return None


class OpenAICompatClient:
    """ModelClient 协议实现（结构化子类型，ScriptedModel 同形）。

    chat 参数 = 测试注入缝：生产不传（构造 ChatOpenAI），
    测试传桩（任何带 .invoke(messages) 的对象）即零网络跑协议面。
    """

    def __init__(
        self, model: str, api_key: str, base_url: str = "", *, chat: Any = None
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._chat = chat if chat is not None else _default_chat(model, api_key, base_url)

    def complete(
        self, messages: Sequence[Mapping[str, Any]], *, role: str, thread_id: str
    ) -> ModelResult:
        """消息字典直喂（langchain 接受 OpenAI 形 dict）；role/thread_id
        为账单挂钩参数（本客户端自身不消费——MeteredModel 层入账）。"""
        response = self._chat.invoke([dict(m) for m in messages])
        return ModelResult(text=_response_text(response), usage=_response_usage(response))


__all__ = ["OpenAICompatClient", "normalize_base_url"]
