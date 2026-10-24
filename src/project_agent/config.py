"""应用级首启配置：首次问一次模型/API 写盘，之后零提问直达。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


class IO(Protocol):
    def read_line(self) -> str | None: ...
    def write_line(self, text: str) -> None: ...


@dataclass(frozen=True)
class AppConfig:
    main_model: str
    api_key: str
    base_url: str = ""
    sub_model: str = ""


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> AppConfig | None:
        if not self._path.exists():
            return None
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return AppConfig(
            main_model=data["main_model"],
            api_key=data["api_key"],
            base_url=data.get("base_url", ""),
            sub_model=data.get("sub_model", ""),
        )

    def save(self, config: AppConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _prompt(io: IO, text: str, *, required: bool) -> str:
    io.write_line(text)
    line = io.read_line()
    value = (line or "").strip()
    if required and not value:
        raise RuntimeError("必填配置缺失（输入结束或为空）")
    return value


def ensure_config(store: ConfigStore, io: IO) -> AppConfig:
    """已有配置零提问直达；缺失则首启问卷一次并写盘。"""
    existing = store.load()
    if existing is not None:
        return existing

    config = AppConfig(
        main_model=_prompt(io, "主模型名称（如 deepseek-chat）:", required=True),
        api_key=_prompt(io, "API key:", required=True),
        base_url=_prompt(io, "API base URL（回车跳过）:", required=False),
        sub_model=_prompt(io, "子角色模型（回车=同主模型）:", required=False),
    )
    store.save(config)
    return config
