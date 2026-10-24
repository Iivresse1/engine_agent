# Project Agent

CLI 项目构建 agent：用户丢进一个想法，agent 通过 grilling 式问答增量构建项目文档包。
LangGraph 单一大图 + 断点协议（图内零 interrupt）+ 隔离红线（角色历史私有）。

设计文档：`.scratch/project-agent/spec.md`（spec v1.1）· 决策台账 `.scratch/project-agent/decisions.md` ·
术语表 `GLOSSARY.md` · ADR `docs/adr/`。

## 运行

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
.venv\Scripts\project-agent            # 首启问一次模型/API，之后直达会话
.venv\Scripts\project-agent --config <path>   # 指定配置文件（测试/多环境）
```

## 测试

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest -q -m replay   # 只跑会话回放（主接缝）
```

测试与主项目物理分隔：src 布局主包 + 独立 `tests/` 树 + extras 依赖组（`test`）+ 零反向 import。
测试替身（可编程假模型 / 假 shell / tmp 工作区）全部住在 `tests/doubles/`，不随主包分发。
