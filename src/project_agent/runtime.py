"""真模型运行时装配：config.env → 客户端/账单/旁路/文档区 一站式。

cli.py 只做解析与生命周期，模型面全部在此装配（可注入 client_factory，
测试零网络）：
- 主/廉价客户端各包 MeteredModel，共用同一 TokenLedger（Q39 本地账单，
  落 --state 同目录 ledger.json）；
- cheap = sub_model（缺省同主模型）——cheap_model 非 None 即挂压缩横切；
- AskBypass 独立 thread（thread_id 加 "-ask" 后缀）：旁路问答历史与主线
  checkpointer 状态物理隔离（ADR-0002）；
- ReplHost 侧 SharedDocs 与 build_graph 内部实例磁盘同源（ADR-0004：
  磁盘文档为共享介质，旁路直读磁盘天然最新）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from project_agent.ask_agent import AskBypass
from project_agent.config import AppConfig
from project_agent.ledger import MeteredModel, TokenLedger
from project_agent.openai_client import OpenAICompatClient
from project_agent.shared_docs import SharedDocs

ClientFactory = Callable[[str, str, str], Any]


@dataclass(frozen=True)
class ModelRuntime:
    """装配产物：cli.py 喂给 build_graph 与 ReplHost 的全部模型面。"""

    model: Any
    cheap_model: Any
    shared_docs: SharedDocs
    ask_bypass: AskBypass
    ledger: TokenLedger


def build_model_runtime(
    config: AppConfig,
    *,
    ledger_path: Path,
    workspace_root: Path,
    thread_id: str,
    client_factory: ClientFactory = OpenAICompatClient,
) -> ModelRuntime:
    """config → 运行时。client_factory 注入缝：测试传桩（签名同
    OpenAICompatClient(model, api_key, base_url)）即零网络全链路。"""
    ledger = TokenLedger(ledger_path)
    main = MeteredModel(
        client_factory(config.main_model, config.api_key, config.base_url), ledger
    )
    sub_name = config.sub_model or config.main_model
    if sub_name == config.main_model:
        cheap = main  # 缺省同主模型：同一 MeteredModel（同一账单角色流）
    else:
        cheap = MeteredModel(
            client_factory(sub_name, config.api_key, config.base_url), ledger
        )
    shared_docs = SharedDocs(workspace_root)
    ask_bypass = AskBypass(main, shared_docs, f"{thread_id}-ask")
    return ModelRuntime(
        model=main,
        cheap_model=cheap,
        shared_docs=shared_docs,
        ask_bypass=ask_bypass,
        ledger=ledger,
    )


__all__ = ["ModelRuntime", "build_model_runtime"]
