# 14: UX-1 壳票 —— engine 命令 + tkinter 配置窗口 + 问卷重编排

**Status:** done（2026-10-25 实现，854 测试绿零警告，ruff 干净）
**类型:** UX 壳票（Q65 五裁定落地）
**开票:** 2026-10-25

**实现记（收口）**：
- engine 命令：pyproject scripts 只留 `engine`（旧名删除）；`--state` 默认 `<cwd>/.project-agent/state.db`；实测 `engine.exe` 就位、旧 exe 消失、state/ledger/session 三件落项目目录。
- 问卷重编排：onboarding 四问删到一问（guidance_pref）；ask_tasks 瘦身为简报直写；guidance_trigger 承担指引一问发射/消费/user_mode 推导；入口路由 +guidance_pref 行 + END_MAP 补键。
- tkinter 窗口（gui_config.py）：六控件 + 测试连接按钮（httpx 惰性导入——Q39 红线哨兵加"顶层 import 即倒退"断言）；纯函数层 12 测试零 GUI。
- AppConfig +decision_mode（.env 兼容旧文件→ai_review）；终端 fallback 补第五问。
- **三处 falsy/子串陷阱修正**：off 是合法已设值（entry_route 与 guidance_trigger 判定）、"不需要"含"需要"（keyword 否定前置）。
- 冒烟（隔离目录）：开场语→简报直写→choice（模型实时推荐）→指引一问四选→"需要"落定 auto/novice 全通。
- 测试 839→854（+18 新：gui_config 12 + restructured_flow 6；-3 随四问删除的旧用例）；128 例旧测试机械适配（子代理五规则分派）。

## 目标

1. `engine` 命令（废弃 `project-agent` 旧名）+ state 每项目化
2. tkinter 首启配置窗口（含测试连接按钮）+ 终端 fallback
3. 问卷重编排：①"今天要做什么呢？"开场语 ②build_ways ③指引一问（后移）；user_mode 由指引答案推导；decision_mode/skill_packs 移出问卷

## 钉死的设计裁定（实现零决策）

### A. engine 命令与路径

- pyproject `[project.scripts]`：**只留** `engine = "project_agent.cli:main"`（旧名 `project-agent` 删除——Q65 废弃裁定，无外部用户）。
- cli.py：`argparse.ArgumentParser(prog="engine")`；`--state` 默认改 **`<cwd>/.project-agent/state.db`**（每项目断点；session.json/ledger.json 同目录）；`--config` 保持全局 `~/.project-agent/config.env`。`.gitignore` 已有 `.project-agent/` 无需改。
- banner 两行：`"Project Agent。输入 /help 查看命令。"` + 空行 + `"今天要做什么呢？"`（Q65 裁定①：开场提示语；用户首条自由文本即首条图输入——现有"首条自由文本进图"架构零改动）。

### B. 问卷重编排（onboarding.py / nodes.py / routing.py / repl.py）

**onboarding.py**：`QUESTIONNAIRE` 删到只剩 guidance_pref 一题（其余三题删除）：

| 字段 | question_text | explanation | options | values | keywords |
|---|---|---|---|---|---|
| guidance_pref | 需要每轮给出指引帮助更好的理解项目吗 —— 构建时配讲解 | 讲解会说明每轮为什么这么做、涉及哪些技术，边构建边学 | `需要 —— 每轮自动附一段讲解`、`先问我 —— 讲不讲当场决定`、`不需要 —— 我自己看得懂` | auto/ask/off | 需要→auto、先问/问我/当场→ask、不需要/不用/看得懂→off |

`question_for`/`interpret_answer`/`next_unset_field` 复用不动（单题表照跑）。`guidance_mode_mapping` 不动。

**nodes.py ask_tasks_node 瘦身**：四问循环删除——task_brief 已设 → {}；上轮 question（指引）答案由 guidance_trigger 消费（见下）；其余输入 → 从首条人类消息写 task_brief + round_end（`任务简报已记录：{brief}`）。**不再发任何 question**。

**guidance_trigger_node 改造**（指引一问的发射与消费，纯代码）：

- `guidance_pref` 已设 → 现行纯映射写 guidance_mode，`{}` 零改动路径保持。
- `guidance_pref` 未设 **且** task_brief/build_way 已设 → 发 question 断点（B 节表 payload，asker=actor）。
- 上轮 question 且 guidance_pref 未设 → 取最新人类消息 `interpret_answer`：
  - 可解释 → 写 `guidance_pref` + **`user_mode` 推导**（auto/ask→"novice"；off→"experienced"）+ guidance_mode 映射 + round_end（`指引偏好已记录`）
  - 不可解释 → 重发同一 question（幂等）
- 拓扑零改动：`_after_build_ways` 已有 GUIDANCE_TRIGGER 分支；`add_edge(GUIDANCE_TRIGGER, END)` 已存在。

**routing.py 新行**（行 3 前插）：`task_brief 已设 + build_way 已设 + guidance_pref 未设（None/""）` → GUIDANCE_TRIGGER（END_MAP 已含该键）。`entry_route` 加对应判定（在 PROPOSALS 行前、build_way 判定后）。删除行 2/行 4/行 5 的 user_mode 问卷路由（`user_mode novice → ASK_TASKS` 两行）。

**repl.py ReplHost 种子注入**：构造参数新增 `initial_dashboard: Mapping[str, Any] | None = None`。首条自由文本 `_run_round` 的 update 里，若 `self._last_state` 无 `decision_mode`/`skill_packs` 值则并入（cli.py 传 `{"decision_mode": config.decision_mode, "skill_packs": ["default"]}`——decision_mode 从配置窗口来，skill_packs 默认包 Q65 裁定）。已续跑会话（last_state 非空有值）跳过。

**user_mode 消费面核对**（推导替代问卷后语义保持）：actor 提示词 `用户编程基础：{user_mode}`（nodes.py 282/430 行区）继续生效——推导值 novice/experienced 与问卷值同词汇；`guidance_mode_mapping` 的 novice 兜底继续生效；`_ask` novice_hint 逻辑随四问删除一起消亡。

### C. tkinter 配置窗口（gui_config.py 新模块）

- **触发**：cli.py 首启（`ensure_config` 返回 None）时先尝试 GUI：`collect_config_gui(defaults) -> AppConfig | None`。窗口关闭/取消/异常 → 返回 None → 终端问卷 fallback（现有 `_prompt` 流程零改动）。非交互/无 tkinter（ImportError/无显示）→ 直接 fallback。
- **窗口字段**（Q65 裁定）：主模型名（必填）、API key（必填，`show="*"`）、base URL（可空）、子角色模型（可空）、**决策模式开关**（默认开=ai_review，标签"AI 自动审核（关=全部人工确认）"）、**测试连接按钮**。
- **测试连接**：`test_connection(model, api_key, base_url) -> tuple[bool, str]`——httpx POST `{base}/chat/completions`（body `{"model": model, "messages": [{"role":"user","content":"ping"}], "max_tokens": 1}`，超时 10s）。base_url 经 `normalize_base_url`（空 → `https://api.openai.com/v1`，与 ChatOpenAI 默认一致）。返回 (ok, 摘要)：2xx → (True, "连接正常（HTTP {code}")；非 2xx/异常 → (False, 短错误摘要)。按钮点击 → 状态行显示"测试中…"→ 结果；**不阻塞保存**（测试失败可仍选择保存）。
- **AppConfig 扩展**：`decision_mode: str = "ai_review"`（受控 "ai_review"|"manual"）；`render_env`/`parse_env`/`_FIELDS` 加该键（尾部）；旧 env 无此键 → 默认 ai_review（向后兼容）。cli.py 种子传 `config.decision_mode`。
- **可测性**：窗口逻辑拆两层——纯函数 `form_fields_to_config(values: Mapping[str,str]) -> AppConfig | None`（校验必填/归一）+ tkinter 壳（壳不单测，注入 `Tk` 不可用时全路径走 fallback 有测试）。`test_connection` 注入 `transport` 参数（httpx.MockTransport 桩）零网络单测。
- tkinter 为标准库（Windows Python 自带）——不进依赖。

### D. 契约回填（收口必做）

- spec v1.7：首启两层节改写（应用级=GUI 窗口+终端 fallback；项目级=build_ways 后指引一问）；仪表盘 user_mode/guidance_pref 消费说明更新（user_mode 推导自指引答案）；路由真值表 +guidance_trigger 行、-user_mode 问卷两行；断点序列图（question 行触发列加"指引一问"）。
- `test_breakpoint_protocol.py::test_dashboard_fields_cover_spec_contract` 字段集不变（四字段全保留在 Dashboard——user_mode/decision_mode/skill_packs 仍是仪表盘字段，只是写入源变了）。
- GLOSSARY 若有"首启问卷四问"表述 → 改两问序（①开场语②build_ways③指引）。

## 切片（5，末片纯收口）

1. engine 命令/banner/state 每项目/AppConfig.decision_mode + env 兼容 + cli 接线 + 种子注入
2. 问卷重编排：onboarding 删题 + ask_tasks 瘦身 + guidance_trigger 改造（发射/消费/user_mode 推导）+ 路由新行
3. gui_config.py：窗口 + form_fields_to_config + test_connection（transport 注入）+ cli 首启接线 + fallback
4. 测试：新测试（gui_config/种子注入/guidance_trigger 断点流/user_mode 推导/路由新行）+ 旧测试大适配（test_ask_tasks_flow/test_onboarding/test_entry_router/test_graph_replay/test_repl_flow/test_build_ways 的问卷段）
5. 合并收口：全量绿零警告 + ruff + spec v1.7 + 票收口 + 台账 Q67 + 提交 + 推远端

## 验收

- 全量测试绿零警告（filterwarnings=error 不动）
- 回放：首条文本→简报 round→次条→build_ways choice→决议→**指引 question→答案→guidance_mode 落定 + user_mode 推导**→planner 轮
- `engine` 命令可跑；旧名 `project-agent` 不再注册
- state.db/session.json/ledger.json 落 `<cwd>/.project-agent/`
- 首启无 config → tkinter 窗口（或 fallback 终端问卷）；测试连接按钮实测
- spec/契约表/代码三者一致
