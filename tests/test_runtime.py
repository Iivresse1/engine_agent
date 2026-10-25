"""运行时装配协议面（零网络：client_factory 桩注入）。"""

from __future__ import annotations

from project_agent.config import AppConfig
from project_agent.runtime import build_model_runtime


class _StubClient:
    """OpenAICompatClient 签名形桩：记录构造参数。"""

    def __init__(self, model: str, api_key: str, base_url: str) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url


def test_runtime_assembles_metered_model_and_bypass(tmp_path):
    made: list[_StubClient] = []

    def factory(model: str, api_key: str, base_url: str) -> _StubClient:
        client = _StubClient(model, api_key, base_url)
        made.append(client)
        return client

    config = AppConfig(
        main_model="deepseek-chat",
        api_key="sk-x",
        base_url="api.deepseek.com",
        sub_model="deepseek-reasoner",
    )
    runtime = build_model_runtime(
        config,
        ledger_path=tmp_path / "ledger.json",
        workspace_root=tmp_path,
        thread_id="t1",
        client_factory=factory,
    )
    # 主 + 廉价两个客户端（sub_model 显式不同 → 各建一个）
    assert [c.model for c in made] == ["deepseek-chat", "deepseek-reasoner"]
    # MeteredModel 包装（协议面：complete 委托内层并可能入账）
    assert runtime.model is not runtime.cheap_model
    assert runtime.model._inner is made[0]  # noqa: SLF001（协议面测试）
    assert runtime.cheap_model._inner is made[1]  # noqa: SLF001
    # 账单路径落指定位置；SharedDocs 指向工作区
    assert runtime.ledger._path == tmp_path / "ledger.json"  # noqa: SLF001
    assert runtime.shared_docs.root == tmp_path
    # AskBypass 独立 thread（"-ask" 后缀与主线隔离）
    assert runtime.ask_bypass._thread_id == "t1-ask"  # noqa: SLF001


def test_runtime_sub_model_default_shares_main(tmp_path):
    """sub_model 缺省（空）→ cheap = 主（同一 MeteredModel，一次构造）。"""
    made: list[_StubClient] = []

    def factory(model: str, api_key: str, base_url: str) -> _StubClient:
        client = _StubClient(model, api_key, base_url)
        made.append(client)
        return client

    config = AppConfig(main_model="deepseek-chat", api_key="sk-x", base_url="", sub_model="")
    runtime = build_model_runtime(
        config,
        ledger_path=tmp_path / "ledger.json",
        workspace_root=tmp_path,
        thread_id="t9",
        client_factory=factory,
    )
    assert len(made) == 1
    assert runtime.model is runtime.cheap_model
    assert runtime.ask_bypass._thread_id == "t9-ask"  # noqa: SLF001


def test_runtime_metered_records_to_ledger(tmp_path):
    """端到端账单链：MeteredModel.complete → TokenLedger.record → 落盘。"""
    from project_agent.model_client import ModelResult, ModelUsage

    class _Scripted:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, *, role: str, thread_id: str) -> ModelResult:
            self.calls += 1
            return ModelResult(text="ok", usage=ModelUsage(input_tokens=5, output_tokens=2))

    inner = _Scripted()
    config = AppConfig(main_model="m", api_key="k", base_url="", sub_model="")
    runtime = build_model_runtime(
        config,
        ledger_path=tmp_path / "ledger.json",
        workspace_root=tmp_path,
        thread_id="t2",
        client_factory=lambda *a: inner,
    )
    result = runtime.model.complete(
        [{"role": "user", "content": "q"}], role="actor", thread_id="t2"
    )
    assert result.text == "ok"
    usage = runtime.ledger.usage_for("t2")
    assert usage["actor"].input_tokens == 5
    assert usage["actor"].output_tokens == 2
    assert usage["actor"].calls == 1
    assert (tmp_path / "ledger.json").exists()
