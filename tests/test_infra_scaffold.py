"""测试基建脚手架自检：假模型 / 假 shell / 工作区隔离。"""

from __future__ import annotations

import pytest

from project_agent.model_client import ModelClient, ModelResult, ModelUsage
from tests.doubles.fake_model import ScriptedModel
from tests.doubles.fake_shell import RecordingShell


def test_scripted_model_satisfies_model_client_seam():
    model = ScriptedModel(["第一手", "第二手"])
    assert isinstance(model, ModelClient)  # 结构化满足协议（runtime_checkable）

    r1 = model.complete([{"role": "user", "content": "q"}], role="actor", thread_id="t1")
    r2 = model.complete([], role="verifier", thread_id="t1")

    assert r1.text == "第一手"
    assert r2.text == "第二手"
    assert (r1.usage.input_tokens, r1.usage.output_tokens) == (10, 5)
    assert model.calls[0]["role"] == "actor"
    assert model.calls[1]["role"] == "verifier"
    assert model.calls[0]["messages"][0]["content"] == "q"


def test_scripted_model_exhaustion_raises():
    model = ScriptedModel([])
    with pytest.raises(AssertionError):
        model.complete([], role="actor", thread_id="t")


def test_scripted_model_accepts_preset_model_result():
    preset = ModelResult(text="带用量", usage=ModelUsage(input_tokens=100, output_tokens=50))
    model = ScriptedModel([preset])
    assert model.complete([], role="actor", thread_id="t") is preset


def test_recording_shell_records_and_presets():
    shell = RecordingShell(outputs={"git status": "clean"}, denied=("rm -rf /",))
    assert shell.run("git status") == "clean"
    with pytest.raises(PermissionError):
        shell.run("rm -rf /")
    assert shell.calls == ["git status", "rm -rf /"]


def test_workspaces_are_isolated(make_workspace):
    w1 = make_workspace("a")
    w2 = make_workspace("b")
    w1.config_path.parent.mkdir(parents=True, exist_ok=True)
    w1.config_path.write_text("{}", encoding="utf-8")

    assert w1.root != w2.root
    assert w1.config_path != w2.config_path
    assert not w2.config_path.exists()
