"""应用级首启配置：首次问一次模型/API 写盘，之后零提问直达。

v1.5 接线票：存储格式由 json 切 .env（KEY=VALUE 平面格式）——
密钥文件惯例 + 零新解析依赖（PyYAML 不进依赖树）；旧 config.json
首读自动迁移（读 json → 写 .env → 删 json，内容无损）。

BOM 容错：Windows PowerShell 管道/写盘易带 UTF-8 BOM（\ufeff），
读取时先剥（首键名 otherwise 变 "\ufeffmain_model" 静默丢配置）；
交互问卷输入行同样剥（冒烟实测伪影）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_BOM = "\ufeff"

# .env 字段序（写盘顺序即首启字段顺序；decision_mode 尾部——14 票 GUI 开关）
_FIELDS = ("main_model", "api_key", "base_url", "sub_model", "decision_mode")


class IO(Protocol):
    def read_line(self) -> str | None: ...
    def write_line(self, text: str) -> None: ...


@dataclass(frozen=True)
class AppConfig:
    main_model: str
    api_key: str
    base_url: str = ""
    sub_model: str = ""
    decision_mode: str = "ai_review"  # 14 票：GUI 开关落盘（"ai_review"|"manual"）


def _strip_bom(text: str) -> str:
    return text.lstrip(_BOM)


def parse_env(text: str) -> dict[str, str]:
    """.env 文本 → dict：KEY=VALUE 逐行；空行/# 注释跳过；
    引号包裹值剥引号；首行 BOM 剥；无 = 的行跳过（容错不抛）。"""
    values: dict[str, str] = {}
    for line in _strip_bom(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def render_env(config: AppConfig) -> str:
    """AppConfig → .env 文本（固定字段序 + 尾换行）。"""
    lines = [f"{field}={getattr(config, field)}" for field in _FIELDS]
    return "\n".join(lines) + "\n"


class ConfigStore:
    """配置存取：.env 主格式；旧 config.json 首读自动迁移。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def _legacy_path(self) -> Path:
        """同目录同名 .json（config.env → config.json）。"""
        return self._path.with_suffix(".json")

    def load(self) -> AppConfig | None:
        if self._path.exists():
            values = parse_env(self._path.read_text(encoding="utf-8"))
            return self._config_from(values)
        if self._legacy_path.exists():
            # 旧格式迁移：读 json → 写 .env → 删 json（一次性，内容无损）
            data = json.loads(self._legacy_path.read_text(encoding="utf-8"))
            config = AppConfig(
                main_model=data["main_model"],
                api_key=data["api_key"],
                base_url=data.get("base_url", ""),
                sub_model=data.get("sub_model", ""),
            )
            self.save(config)
            self._legacy_path.unlink()
            return config
        return None

    def save(self, config: AppConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(render_env(config), encoding="utf-8")

    @staticmethod
    def _config_from(values: dict[str, str]) -> AppConfig | None:
        """必填缺失（main_model/api_key）→ None：视同无配置，问卷重建。"""
        main_model = values.get("main_model", "")
        api_key = values.get("api_key", "")
        if not main_model or not api_key:
            return None
        # decision_mode 受控归一：非法值/缺省 → ai_review（14 票默认）
        decision_mode = values.get("decision_mode", "")
        if decision_mode not in ("ai_review", "manual"):
            decision_mode = "ai_review"
        return AppConfig(
            main_model=main_model,
            api_key=api_key,
            base_url=values.get("base_url", ""),
            sub_model=values.get("sub_model", ""),
            decision_mode=decision_mode,
        )


def _prompt(io: IO, text: str, *, required: bool) -> str:
    io.write_line(text)
    line = io.read_line()
    # BOM 剥离：pwsh 管道首行常带 \ufeff（冒烟实测），不剥则污染首字段
    value = _strip_bom(line or "").strip()
    if required and not value:
        raise RuntimeError("必填配置缺失（输入结束或为空）")
    return value


def ensure_config(store: ConfigStore, io: IO) -> AppConfig:
    """已有配置零提问直达；缺失则首启问卷一次并写盘（终端 fallback 形态）。"""
    existing = store.load()
    if existing is not None:
        return existing

    config = AppConfig(
        main_model=_prompt(io, "主模型名称（如 deepseek-chat）:", required=True),
        api_key=_prompt(io, "API key:", required=True),
        base_url=_prompt(io, "API base URL（回车跳过）:", required=False),
        sub_model=_prompt(io, "子角色模型（回车=同主模型）:", required=False),
        decision_mode=(
            _prompt(io, "决策模式（回车=AI 自动审核；输 manual=全部人工）:", required=False)
            or "ai_review"
        ),
    )
    store.save(config)
    return config


__all__ = ["AppConfig", "ConfigStore", "ensure_config", "parse_env", "render_env"]
