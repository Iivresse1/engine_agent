"""tkinter 首启配置窗口（14 票）：Windows 自带观感，填完落 config.env。

分层可测：纯函数层（form_fields_to_config / test_connection）零 GUI 依赖
可注入桩单测；tkinter 壳（collect_config_gui）不单测——ImportError/无显示
/取消/异常全路径返回 None，cli.py 据此退终端问卷 fallback。

测试连接：httpx POST {base}/chat/completions 1-token ping（2xx 即通，
非 2xx/超时/网络错误 → 失败摘要）。不阻塞保存——测试失败仍可保存，
坏 key 交给用户自己决定。
"""

from __future__ import annotations

from typing import Any, Mapping

from project_agent.config import AppConfig
from project_agent.openai_client import normalize_base_url

_DEFAULT_BASE = "https://api.openai.com/v1"


def _httpx():
    """httpx 惰性导入（Q39 红线：主包顶层 import 零网络库；测试连接才加载）。"""
    import httpx

    return httpx


def form_fields_to_config(values: Mapping[str, str]) -> AppConfig | None:
    """表单值 → AppConfig；必填缺失（模型/key）→ None。

    decision_mode 归一：非 "manual" 一律 "ai_review"（默认开）。
    """
    main_model = (values.get("main_model") or "").strip()
    api_key = (values.get("api_key") or "").strip()
    if not main_model or not api_key:
        return None
    decision_mode = "manual" if values.get("decision_mode") == "manual" else "ai_review"
    return AppConfig(
        main_model=main_model,
        api_key=api_key,
        base_url=(values.get("base_url") or "").strip(),
        sub_model=(values.get("sub_model") or "").strip(),
        decision_mode=decision_mode,
    )


def test_connection(
    model: str,
    api_key: str,
    base_url: str = "",
    *,
    transport: Any = None,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """1-token ping：POST {base}/chat/completions，2xx → (True, 摘要)。

    transport 注入缝：httpx.MockTransport 桩零网络单测；生产走默认网络。
    base_url 空 → openai 官方默认端点（与 ChatOpenAI 一致）。
    """
    base = normalize_base_url(base_url) or _DEFAULT_BASE
    url = f"{base}/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    httpx = _httpx()
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.post(url, json=body, headers=headers)
        if 200 <= response.status_code < 300:
            return True, f"连接正常（HTTP {response.status_code}）"
        detail = response.text[:80]
        return False, f"HTTP {response.status_code}：{detail}"
    except httpx.HTTPError as exc:
        return False, f"连接失败：{exc.__class__.__name__}"


def collect_config_gui() -> AppConfig | None:
    """弹 tkinter 窗口收集配置；取消/关闭/无 tkinter/异常 → None（退 fallback）。

    全异常兜底：GUI 层任何失败都不阻塞 CLI 启动。
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return None
    try:
        root = tk.Tk()
    except Exception:
        return None  # 无显示环境（无 X/远程会话）
    root.title("Project Agent 配置")
    root.resizable(False, False)

    result: dict[str, str] = {}

    fields: list[tuple[str, str]] = [
        ("主模型名称（如 deepseek-chat）", "main_model"),
        ("API key", "api_key"),
        ("API base URL（可空，如 api.deepseek.com）", "base_url"),
        ("子角色模型（可空=同主模型）", "sub_model"),
    ]
    entries: dict[str, tk.Entry] = {}
    for row, (label, key) in enumerate(fields):
        ttk.Label(root, text=label).grid(column=0, row=row, sticky="w", padx=10, pady=4)
        entry = ttk.Entry(root, width=44, show="*" if key == "api_key" else "")
        entry.grid(column=1, row=row, padx=10, pady=4)
        entries[key] = entry

    decision_var = tk.BooleanVar(value=True)  # 默认开 = ai_review
    ttk.Checkbutton(
        root,
        text="AI 自动审核（不勾=全部人工确认）",
        variable=decision_var,
    ).grid(column=0, row=len(fields), columnspan=2, sticky="w", padx=10, pady=4)

    status_var = tk.StringVar(value="")
    ttk.Label(root, textvariable=status_var, foreground="#666").grid(
        column=0, row=len(fields) + 1, columnspan=2, sticky="w", padx=10
    )

    def _collect() -> dict[str, str]:
        values = {key: entry.get() for key, entry in entries.items()}
        values["decision_mode"] = "ai_review" if decision_var.get() else "manual"
        return values

    def _on_test() -> None:
        values = _collect()
        if not values["main_model"] or not values["api_key"]:
            status_var.set("请先填模型名与 API key")
            return
        status_var.set("测试中…")
        root.update_idletasks()
        ok, message = test_connection(
            values["main_model"], values["api_key"], values["base_url"]
        )
        status_var.set(("✓ " if ok else "✗ ") + message)

    def _on_save() -> None:
        result.update(_collect())
        root.destroy()

    ttk.Button(root, text="测试连接", command=_on_test).grid(
        column=0, row=len(fields) + 2, sticky="e", padx=10, pady=6
    )
    ttk.Button(root, text="保存并开始", command=_on_save).grid(
        column=1, row=len(fields) + 2, sticky="e", padx=10, pady=6
    )
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()

    if not result:
        return None  # 直接关窗/取消
    return form_fields_to_config(result)


__all__ = ["collect_config_gui", "form_fields_to_config", "test_connection"]
