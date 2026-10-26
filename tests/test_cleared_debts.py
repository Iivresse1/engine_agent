"""清欠账：/teach-me 恢复路径（13 票 B 节）与桌面密钥文件读取（Q64）。"""

from __future__ import annotations

from project_agent.config import AppConfig, ConfigStore, ensure_config
from project_agent.repl import ReplHost
from tests.doubles.scripted_io import ScriptedIO


class _StubApp:
    def invoke(self, update, config):
        return {"turn_end_reason": "round", "turn_end_payload": {}}


# ---- /teach-me（13 票 B 节裁定的恢复路径，spec 与代码此前双缺）----

def test_teach_me_command_is_registered() -> None:
    """/teach-me 必须在命令表内（此前 spec 与代码都缺这一条）。"""
    from project_agent.repl import _COMMANDS

    assert "/teach-me" in _COMMANDS


def test_teach_me_query_without_argument_shows_state() -> None:
    io = ScriptedIO(["/teach-me", "/exit"])
    host = ReplHost(_StubApp(), io, "t")
    host.run()
    assert any("深度教学偏好" in line for line in io.outputs)


def test_teach_me_off_clears_preference() -> None:
    """核心裁定：`/teach-me off` 清回 `""`（恢复每轮四选询问）。"""
    io = ScriptedIO(["/teach-me always", "/teach-me off", "/status", "/exit"])
    host = ReplHost(_StubApp(), io, "t")
    host.run()
    assert host._last_state.get("teach_me_pref") == ""
    assert any("已关闭" in line for line in io.outputs)


def test_teach_me_always_sets_preference() -> None:
    io = ScriptedIO(["/teach-me always", "/exit"])
    host = ReplHost(_StubApp(), io, "t")
    host.run()
    assert host._last_state.get("teach_me_pref") == "always"


def test_teach_me_off_from_always_roundtrip() -> None:
    """always → off → always 往返（用户可否决，见 13 票裁定）。"""
    io = ScriptedIO(["/teach-me always", "/teach-me off", "/teach-me always", "/exit"])
    host = ReplHost(_StubApp(), io, "t")
    host.run()
    assert host._last_state.get("teach_me_pref") == "always"


def test_teach_me_unknown_value_prompts_usage() -> None:
    io = ScriptedIO(["/teach-me banana", "/exit"])
    host = ReplHost(_StubApp(), io, "t")
    host.run()
    assert any("未识别取值" in line for line in io.outputs)
    assert not host._last_state.get("teach_me_pref")


def test_teach_me_off_aliases() -> None:
    for alias in ("off", "关", "关闭", "不用"):
        io = ScriptedIO([f"/teach-me {alias}", "/exit"])
        host = ReplHost(_StubApp(), io, "t")
        host.run()
        assert host._last_state.get("teach_me_pref") == "", f"别名 {alias} 应清空"


# ---- 桌面密钥文件读取（Q64 用户明示，代码此前无此路径）----

def test_api_key_read_from_desktop_storage(tmp_path, monkeypatch) -> None:
    """从 `<home>/Desktop/storage/apikey.txt` 读到裸 key。"""
    home = tmp_path / "home"
    storage = home / "Desktop" / "storage"
    storage.mkdir(parents=True)
    (storage / "apikey.txt").write_text("sk-from-desktop\n", encoding="utf-8")
    monkeypatch.delenv("PROJECT_AGENT_API_KEY_FILE", raising=False)
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(home))

    from project_agent.config import _api_key_from_desktop

    assert _api_key_from_desktop() == "sk-from-desktop"


def test_api_key_read_from_key_value_form(tmp_path, monkeypatch) -> None:
    """支持 `api_key=xxx` 形态（不只有裸 key）。"""
    home = tmp_path / "home"
    storage = home / "Desktop" / "storage"
    storage.mkdir(parents=True)
    (storage / "apikey.txt").write_text("# 注释\napi_key=sk-kv-form\n", encoding="utf-8")
    monkeypatch.delenv("PROJECT_AGENT_API_KEY_FILE", raising=False)
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(home))

    from project_agent.config import _api_key_from_desktop

    assert _api_key_from_desktop() == "sk-kv-form"


def test_api_key_desktop_bom_stripped(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    storage = home / "Desktop" / "storage"
    storage.mkdir(parents=True)
    (storage / "apikey.txt").write_bytes("\ufeffsk-bom-key\n".encode())
    monkeypatch.delenv("PROJECT_AGENT_API_KEY_FILE", raising=False)
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(home))

    from project_agent.config import _api_key_from_desktop

    assert _api_key_from_desktop() == "sk-bom-key"


def test_api_key_absent_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(tmp_path / "empty_home"))
    monkeypatch.delenv("PROJECT_AGENT_API_KEY_FILE", raising=False)

    from project_agent.config import _api_key_from_desktop

    assert _api_key_from_desktop() == ""


def test_explicit_key_file_overrides_desktop(tmp_path, monkeypatch) -> None:
    """显式 `PROJECT_AGENT_API_KEY_FILE` 独占：不回退桌面探测。"""
    home = tmp_path / "home"
    storage = home / "Desktop" / "storage"
    storage.mkdir(parents=True)
    (storage / "apikey.txt").write_text("sk-desktop\n", encoding="utf-8")
    explicit = tmp_path / "explicit.txt"
    explicit.write_text("sk-explicit\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(home))
    monkeypatch.setenv("PROJECT_AGENT_API_KEY_FILE", str(explicit))

    from project_agent.config import _api_key_from_desktop

    assert _api_key_from_desktop() == "sk-explicit"


def test_explicit_key_file_missing_returns_empty_not_desktop(tmp_path, monkeypatch) -> None:
    """显式路径指向不存在的文件 → 空（**不得**回退桌面）——测试隔离依赖此语义。"""
    home = tmp_path / "home"
    storage = home / "Desktop" / "storage"
    storage.mkdir(parents=True)
    (storage / "apikey.txt").write_text("sk-desktop\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(home))
    monkeypatch.setenv("PROJECT_AGENT_API_KEY_FILE", str(tmp_path / "nope.txt"))

    from project_agent.config import _api_key_from_desktop

    assert _api_key_from_desktop() == ""


def test_onboarding_uses_discovered_key(tmp_path, monkeypatch) -> None:
    """首启：桌面命中密钥 → 只需问模型名与 API key（回车即用发现的）。"""
    home = tmp_path / "home"
    storage = home / "Desktop" / "storage"
    storage.mkdir(parents=True)
    (storage / "apikey.txt").write_text("sk-desktop\n", encoding="utf-8")
    monkeypatch.delenv("PROJECT_AGENT_API_KEY_FILE", raising=False)
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(home))

    io = ScriptedIO(["deepseek-chat", "", "", ""])  # 模型名, api_key回车, base, sub
    store = ConfigStore(tmp_path / "config" / "config.env")
    config = ensure_config(store, io)

    assert config.main_model == "deepseek-chat"
    assert config.api_key == "sk-desktop"
    assert any("storage/apikey.txt" in line for line in io.outputs)


def test_onboarding_config_file_wins_over_desktop(tmp_path, monkeypatch) -> None:
    """已有 config.env 时零提问直达——显式配置优先于约定路径。"""
    home = tmp_path / "home"
    storage = home / "Desktop" / "storage"
    storage.mkdir(parents=True)
    (storage / "apikey.txt").write_text("sk-desktop\n", encoding="utf-8")
    monkeypatch.delenv("PROJECT_AGENT_API_KEY_FILE", raising=False)
    monkeypatch.setenv("PROJECT_AGENT_HOME", str(home))

    store = ConfigStore(tmp_path / "config" / "config.env")
    store.save(AppConfig(main_model="m", api_key="sk-explicit"))
    io = ScriptedIO([])
    config = ensure_config(store, io)
    assert config.api_key == "sk-explicit"
    assert io.outputs == []
