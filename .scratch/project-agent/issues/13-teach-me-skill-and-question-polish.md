# 13: teach-me 技能 + 指引询问真断点 + 全量问题文案润色

**Status:** done（2026-10-25 实现，Lead 直做，839 测试绿零警告，ruff 干净）
**类型:** 功能票（v1.5 接线延续）
**开票:** 2026-10-25（用户裁定：每轮四选含"之后都开"、auto 保持普通指引、勾选存 localStorage、teach-me 先于 UX-1）

**实现记（2026-10-25 收口）**：
- 新模块：rendering.py（问题三层渲染：主体加粗/解释缩进/选项编号，TTY 判定退化）+ teach_me.py（四选解释引擎/run_teach_me 三件落盘/画像与 session 幂等维护）
- 协议：question/choice:build_way +explanation 必填；docs_done 否定词改整词集合（长选项"生成不运行"含"不"字误吞修复）
- actor：起手四选解释（teach/teach_always/skip/brief；brief 掉落身体走 auto 同款指引——guidance_ask_consumed 局部标志防重问）；后置 ask 模式发真断点；teach_me_pref=always 直达 teach
- skills +teach-me（one_liner 逐字进 body 保契约）；state +teach_me_pref
- 测试 +43（821→839）；全量文案断言适配（build_ways/onboarding/ask_tasks_flow/graph_replay/repl_flow/actor_guidance/skills/breakpoint_protocol/docs_done）
- spec v1.6 回填：question/choice:build_way payload 行 +explanation、仪表盘 +teach_me_pref

## 目标

1. ask 模式指引询问从"贴标签"升级为**真 question 断点**（回填 spec L208 本义），四选含"以后都深度教学"
2. 新技能 teach-me：材料包 + 技能全文 → 单发模型调用 → 自包含 HTML 教学页落盘（勾选存 localStorage）
3. **全量问题/选项文案润色**（用户明示："可读性非常差，看到会生气"）——所有提问点改为"加粗主体 —— 不加粗解释"式
4. question payload 增加 `explanation` 字段；REPL 渲染美化（主体加粗）

## 钉死的设计裁定（实现零决策）

### A. 协议形状（最小变更）

- `protocol.py`：`QUESTION` 行 required_payload_fields 追加 `"explanation"`（str）。options **保持 list[str] 不变**——说明织进字符串（"标签 —— 说明"），`_LIST_FIELDS` 校验零改动。
- 发射点全量补 explanation（见 C 节文案表）。
- 契约测试 `test_breakpoint_protocol.py` 断言表同步；spec 断点协议表 question 行回填（v1.6）。

### B. teach_me_pref 状态

- 仪表盘新字段 `teach_me_pref: str = ""`（"" | "always"）。spec 仪表盘表回填。
- ask 模式每轮四选；选"以后都深度教学" → `teach_me_pref="always"`，之后 ask 模式直接生成 teach-me 不再询问。
- 仅 ask 模式消费该字段：auto 恒普通指引（用户裁定）；off 无指引轮。
- 恢复路径：斜杠命令 `/teach-me off` 清回 ""（Lead 裁定记档；用户可否决砍掉）。

### C. 全量文案表（逐字实现，不得改写）

**问卷四问（onboarding.py QUESTIONNAIRE）**——question_text / explanation / options / keywords 全替换：

| 字段 | 新文案 |
|---|---|
| user_mode | 问："你的编程基础 —— 决定 agent 用多大深度和你沟通"；解释："这会影响讲解的详略和术语的密度"；选项：`有编程经验 —— 看得懂代码，直接谈实现`、`编程新手 —— 需要逐步解释每一步在做什么` |
| guidance_pref | 问："新手指引 —— 构建过程中要不要配讲解"；解释："讲解会说明每轮为什么这么做、涉及哪些技术"；选项：`自动讲解 —— 每轮自动附带一段说明`、`每轮问我 —— 讲不讲由我当场决定`、`关闭 —— 不需要讲解`；novice_hint 改："（新手推荐选 1）" |
| decision_mode | 问："关键决策把关 —— 重要选择谁来拍板"；解释："涉及技术选型、文件改动等关键动作时的确认策略"；选项：`AI 自动审核 —— 常规自动通过，高风险才来问我`、`全部人工 —— 每个决策都先经我确认` |
| skill_packs | 问："技能包 —— 内置的工作方法集合，启用吗"；解释："技能是预置的做事套路，比如测试先行、追问压测"；选项：`启用默认包 —— 通用工作方法全量加载`、`暂不启用 —— 以后随时用 /skills 添加` |

keywords 表相应扩（原有词全保留 + 新增长选项的稳定子串：如"看得懂"、"逐步解释"、"当场决定"、"先经我确认"、"/skills"）。novice_hint 判定逻辑不动。

**build_ways（nodes.py BUILD_WAY_OPTIONS / _WAY_BY_LABEL / 静态推荐）**：

- choice payload explanation（CHOICE_BUILD_WAY 行 required 追加 `"explanation"`）："决定 agent 用多重的流程陪你把这个项目做出来"
- options：`对话 —— 像聊天一样推进，不产出文档`、`轻 grill —— 少量追问压测计划，文档极简`、`简化文档 —— 核心 README/TODO，轻量直接`、`完整文档 —— 完整规格/ADR/术语表，适合长期维护`
- `_WAY_BY_LABEL` 键同步换长标签；`_BUILD_WAY_KEYWORDS` 原关键词全保留（子串匹配对长选项仍命中）；recommendation 值用长标签。
- 静态推荐文案不变（"简化文档"+理由 20 字内）。

**docs_done（_DOCS_DONE_OPTIONS）**：`构建 demo —— 生成可运行的基础示例（生成不运行，报错你来贴）`、`跳过 —— 直接进入收尾整理`

**loop_exhausted**：help_text 微调为"已连续 5 轮未通过验收 —— 请人工接管：调整任务简报，或直接告诉 agent 下一步怎么做。"（两处）

**指引询问（新，ask 模式，actor 后置工序）**：

- 问："本轮讲解 —— 要为这轮的产出配一段讲解吗？"
- 解释："讲解会说明这轮做了什么、为什么这么做"
- options 四选：
  1. `简短讲解 —— 一段话说明本轮要点`
  2. `深度教学 —— 生成一页图文教学页（HTML，含可勾选的概念清单）`
  3. `跳过 —— 这轮不需要讲解`
  4. `以后都深度教学 —— 之后每轮自动生成教学页，不再询问`
- asker=`actor`（Role 枚举不扩；awaiting_input_from=actor，答案融主线，同问卷机制）。

### D. 指引询问断点机制（与 ask_tasks 问卷同构）

- **发射**：actor 指引后置工序（现 nodes.py:949-967 区域）：`guidance_mode=="ask"` 且版本门通过时——不再贴 `[指引询问]` 前缀文本，改为 emit question 断点（C 节四选 payload），`guidance_read_version` 对齐照旧写。
- **解释**：actor 节点起手（身体调用之前）检查：上轮 `turn_end_reason=="question"` **且** task_brief 已设 **且** build_way 已设（图内 question 仅问卷/build_ways/指引三处——前两者必不满足此判定，无歧义）。取 `_latest_human_text` 解释：
  - `简短|普通|讲解|1` → 本轮 brief（走原普通指引路径）
  - `深度|教学|教|2` → 本轮 teach
  - `跳过|不要|不用|3` → 本轮 skip（零指引）
  - `以后|都|以后都|4` → 写 `teach_me_pref="always"` 且本轮 teach
  - 解释不了 → 重发同一 question 断点（幂等）
- `teach_me_pref=="always"`：起手不解释直接本轮 teach（不再 emit 询问）。
- 路由零改动：question 断点答案融主线，入口路由主环行已覆盖。

### E. teach-me 生成

- `skills.py`：`SKILLS` 追加 `SkillHead("teach-me", "页面式深度教学：生成可勾选概念的 HTML 教学页")`；`_SKILL_BODY_TEXT["teach-me"]` 写约 200 字技能说明（教学页结构要求、个性化要点、概念清单格式——实现者按既有三技能文风撰写）。
- **单发调用**：`role="ask_agent"`（ModelClient 协议词汇；ADR-0002 隔离——无历史累积）。prompt = 指引材料包（round_summary + notepad + 文档切片）+ teach-me skill body + learner-profile.md（存在则读入）+ teach-me/session.md 概念清单（存在则读入，注明"已掌握的概念不要重教"）。
- **产出落盘**（代码层，模型返回 HTML 全文）：
  - `teach-me/R{n}/index.html`（n=round_count）——经 `shared_docs.write_any`（复用 DemoAgent 路径防护；`write_any` docstring 更新为"DemoAgent 与 teach-me 专用"）
  - `teach-me/learner-profile.md` —— 纯代码维护：首启写基础画像（user_mode、guidance_pref、构建方式、任务简报一行）
  - `teach-me/session.md` —— 纯代码维护：每次 teach-me 追加一行（轮次号 + 日期 + 概念清单标题数）
- **HTML 模板要求**（写进 prompt，钉死）：自包含单文件（内联 CSS，零外链零 JS 依赖）；概念清单每项带 checkbox，勾选状态存 `localStorage`（key=teach-me-R{n}）；中文排版（标题层级/正文行高）；页首标注轮次与日期。
- round_output 渲染一行："教学页已生成：teach-me/R{n}/index.html"（不贴 HTML 全文）。

### F. REPL 渲染（repl.py _invoke_round）

- question 断点专属渲染：`question_text` ANSI 加粗（`\033[1m...\033[0m`），`explanation` 普通缩进，`options` 逐行编号；其余 reason 保持现行 k/v 平铺。
- 渲染函数独立（可单测）；加粗在非 TTY（管道）下退化为原文（`sys.stdout.isatty()` 判定）。

### G. 契约回填（收口必做）

- spec v1.6：断点协议表 question 行 +explanation、CHOICE_BUILD_WAY 行 +explanation；仪表盘 +teach_me_pref
- `test_breakpoint_protocol.py` 契约断言同步
- 既有测试文案断言全量适配（"轻 grill"等长标签替换波及面：test_build_ways/test_repl_flow/test_graph_replay 等——跑全量按红改）

## 切片（5，末片纯收口）

1. 协议 + 渲染：protocol.py 两处 explanation 必填；repl.py question 美化；现有发射点补 explanation；契约测试适配
2. 文案润色：C 节全表落码 + keywords 扩展 + 全量测试文案断言适配
3. 指引询问真断点：D 节机制（发射 + 起手解释 + teach_me_pref）+ 新测试
4. teach-me 生成：E 节全量 + 测试（假模型断言 prompt 含 skill body/profile、落盘三件、round_output 一行）
5. 合并收口：全量绿零警告 + ruff + spec v1.6 + 票收口 + 台账

## 验收

- 821+ 测试全绿零警告（filterwarnings=error 不动）
- 回放：ask 模式下轮终见四选 question 断点；答"4"后 teach_me_pref=always 且当轮生成三件落盘；答"3"当轮零指引
- 管道态无 ANSI 转义污染输出
- spec/契约表/代码三者一致（Q63 纪律）
