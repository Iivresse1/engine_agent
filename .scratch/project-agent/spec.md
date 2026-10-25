# Spec: 项目构建 Agent（Project Agent）v2.1

Status: ready-for-agent
词汇: 严格使用 GLOSSARY.md；遵循 docs/adr/0001–0005
来源: 32 轮 grilling 设计会话 + 实现期裁定（决策台账 .scratch/project-agent/decisions.md，Q1–Q69）

## 版本志

| 版本 | 日期 | 增补 |
|---|---|---|
| v1 | 2026-10-24 | 首发：问题 / 方案 / 用户故事 / 实现裁定 / 测试策略 |
| v1.1 | 2026-10-24 | 图状态契约（仪表盘字段表、私有 key 表、断点协议、入口路由真值表）；断点取代 interrupt（ADR-0001）；测试与主项目物理分隔 |
| v1.2 | 2026-10-25 | 仪表盘补录 02 票问卷四字段；私有 key 表补录决议输入通道（resolution_inputs） |
| v1.3 | 2026-10-25 | 仪表盘 +round_count（【R#】编号源） |
| v1.4 | 2026-10-25 | 仪表盘 +compacted_rounds（压缩溯源） |
| v1.5 | 2026-10-25 | 入口路由真值表随 11/12 票改道更新（docs_done 行、demo 行、skipped 直通）；BUILD_LOG.md 定为【R#】全文载体；/mode、/skills 运行时命令补齐（用户故事 3） |
| v1.6 | 2026-10-25 | question 与 choice:build_way payload +explanation；仪表盘 +teach_me_pref；ask 档指引询问真断点化（四选含 teach-me）——13 票 |
| v1.7 | 2026-10-25 | 14 票问卷重编排：ask_tasks 瘦身为简报直写、指引一问归 guidance_trigger（发射/消费/user_mode 推导）、入口路由 +guidance_pref 行、首启改配置窗口、决策模式/技能包出问卷 |
| v1.8 | 2026-10-25 | **真模型接线（Q64）**：配置格式定 .env、OpenAI 兼容客户端、运行时一站装配、本地账单实际落账、密钥防推送加固 |
| v2.1 | 2026-10-26 | **UX-2 第一片（Q69）**：前后端协议消息契约落地——`PROTOCOL_MESSAGES` 表（6 类下行 + 2 类上行）+ 载荷校验 + 终端降级渲染；`messages.py` 纯翻译层；传输层（WebSocket）仍欠 |
| v2.0 | 2026-10-26 | **本轮回灌（Q65–Q68）**：外观定为 TS/Ink 前端 + Python 后端双运行时（ADR-0005，**冲突以新为准**：原"v1 全 CLI""Web UI/前端已砍""rich/textual 后置"三条作废）；engine 命令与每项目状态；tkinter 仅配置窗口；文案"主体 —— 解释"契约与三层渲染；teach-me 教学页通道；已知欠账清单补录 |

## Problem Statement

用户有一个项目想法，但不知道怎么把它变成一个结构清晰的项目。直接让通用 AI 助手帮忙，得到的是一次性、无法沉淀的对话——聊天记录越滚越长，AI 忘了最初的目标，用户也没学到东西；想边构建边问"为什么用这个技术栈"，只会让构建用的上下文越来越臃肿，token 花在重复搬运历史上。

同时，经验丰富的开发者和零基础的用户需要的是完全不同的构建体验：前者要快、要少打扰；后者要每一步都有人解释"为什么这么做"。

第三层痛点在实现期才显形：**交互本身的可读性**。终端里一句"1. 需要 2. 先问我 3. 不需要"无法承载"选这个的代价是什么"，用户明示"可读性非常差，看到会生气"。选项必须自带解释，讲解必须能脱离滚屏留存。

## Solution

一个本地应用：用户丢进一个想法，通过分档的构建方式（从纯对话到完整项目文档）增量构建出项目文档包，期间可以随时旁路提问学习技术知识——问答与构建共享同一份磁盘文档但对话上下文完全隔离，构建不被提问拖慢，提问不被构建污染。

**形态是双运行时**：TypeScript 前端（React 19 + Ink）负责观感与按键，Python 后端负责图执行与状态；两者只经协议消息对话（ADR-0005）。首启的模型配置窗口是 tkinter（"Windows 观感"仅此一处）。安装与启动只有一条命令 `engine`。

构建全程以轮次为节律：每轮结束交还控制权（断点），用户自由输入融合续跑。开场不设问卷墙——一句"今天要做什么呢？"，用户的第一句话就是任务简报。构建方式四档，之后只问一次"要不要每轮配讲解"，要点讲解的人获得两种形态：一句话讲解，或一页可勾选概念的 HTML 教学页（teach-me）。文档完成后可指令生成可运行 demo（生成不运行，报错由用户粘贴回来、agent 诊断）。上下文工程层（组装/压缩/Notepad/作用域）保证长会话不退化。

## User Stories

### 入口与首启

1. As a 用户, I want 首次启动在一个配置窗口里一次填好模型、API 与决策模式, so that 我不用每次启动都重复设置
2. As a 用户, I want 之后每次启动直接进入会话零提问, so that 我可以立即开始工作
3. As a 用户, I want 用 `/mode`、`/skills` 等斜杠命令随时修改配置, so that 不用重启就能调整
4. As a 有编程基础的用户, I want 默认进入简洁高效的构建流程, so that 少打扰快出活
5. As a 零基础用户, I want agent 从我的指引答案推断我的水平, so that 我不必再额外回答一道"编程基础"题
6. As a 零基础用户, I want 答"需要讲解"后自动获得每轮构建指引, so that 我能边构建边理解发生了什么
7. As a 半懂用户, I want 新手指引做成三态（自动每轮 / 先问我 / 关）, so that 我能按需调节被打扰的程度
8. As a 用户, I want 项目级只问一次指引偏好且问在构建方式之后, so that 提问出现在语义就近的地方而不是开场墙
9. As a 用户, I want 开场只有一句"今天要做什么呢？"且我的第一句话就成为任务简报, so that 我开口即可开工而不必先答问卷
10. As a 用户, I want 配置窗口带"测试连接"按钮, so that key 填错当场知道而不是开跑才炸
11. As a 用户, I want 决策模式在配置窗口里定默认、之后还能 `/mode` 改, so that 安全档位不必每个项目重设
12. As a 用户, I want 技能包默认启用、需要时 `/skills` 增删, so that 开箱即用又保留调整权
13. As a 用户, I want 配置全局、会话状态按项目各存一份, so that 一次配置到处能用、换目录即新会话
14. As a 用户, I want 进程重启后接着上次的断点继续（首答不丢）, so that 我不是每次都要从头说一遍
15. As a 用户, I want 只用一条 `engine` 命令启动、用 pipx 安装, so that 分发与升级不折腾

### 构建方式

16. As a 用户, I want 被问"你想做什么"即我的开场第一句话（ask_tasks）, so that agent 知道我的任务
17. As a 用户, I want 四种构建方式（对话/轻 grill/简化文档/完整文档）带推荐和一句话理由, so that 我能快速选对深度
18. As a 只想聊天的用户, I want 选对话方式后得到 ReAct 循环的普通 agent 体验, so that 小事不必走流程
19. As a 做小脚本的用户, I want 轻方式（IDEA.md 一页纸 + 短 grilling 直达 demo）, so that 轻活不被文档拖慢
20. As a 做个人作品的用户, I want 简化文档集（README+TODO+目录树）, so that 有沉淀但不臃肿
21. As a 做复杂工程的用户, I want 完整文档框架, so that 项目有工程级的纸面基础
22. As a 做复杂工程的用户, I want grilling 到位后并行看到三套构建方案, so that 我能对比技术栈与复杂度取舍
23. As a 做复杂工程的用户, I want 断点处自由选定或融合方案, so that 我不被锁死在单一预设里

### 构建过程

24. As a 用户, I want 构建以轮次为节律、每轮结束交还控制权, so that 我随时可以插话改变方向
25. As a 用户, I want planner 先列出 todo 清单, so that 构建有可见的计划而非黑箱
26. As a 用户, I want todo 清单三态显示（未开始/进行中/完成）, so that 我随时知道进度和当前焦点
27. As a 用户, I want 每轮生成物带【R#】轮次标记, so that 我知道什么是什么时候产生的
28. As a 用户, I want 主角色按项目阶段推荐技能（指令+20字内理由）, so that 我知道下一步可以调什么
29. As a 用户, I want 技能推荐不打断我（AI 审核档）或每条都暂停等我确认（人工裁决档）, so that 打扰程度由我定
30. As a 用户, I want 复杂文档由框架先行、grilling 指引逐步填写, so that 文档不是一次性倒出来而是长出来的

### 学习与提问（旁路）

31. As a 用户, I want `/ask-for-help` 随时切换到旁路问答, so that 疑问不打断构建主线
32. As a 用户, I want 旁路问答读的是项目文档切片而非主对话历史, so that 问"为什么选X"能得到项目语境的答案
33. As a 用户, I want 旁路问答自己的历史独立累积, so that 追问不丢、上下文不串
34. As a 新手用户, I want 每轮构建指引附"为什么这么做+下一步+技术栈文档链接", so that 我在构建中同步学习
35. As a 新手用户, I want 指引出现在主产出之外的独立区域（侧栏/折叠面板）, so that 学习不遮挡构建本身
36. As a 想深入的用户, I want 文档链接经过抓取验证有效, so that 我不被死链浪费

### 讲解与教学（13 票）

37. As a 用户, I want ask 档每轮收到四选（简短讲解/深度教学/跳过/以后都深度教学）, so that 讲解粒度我当场定
38. As a 用户, I want 选"以后都深度教学"后不再被逐轮询问, so that 一次决定长期生效
39. As a 用户, I want 深度教学产出独立 HTML 页（概念清单可勾选、勾选状态记住）, so that 讲解不滚屏、复习有进度
40. As a 用户, I want 教学页落在 `teach-me/R{n}/index.html` 与交付物目录分离, so that 教学产物不污染项目文档
41. As a 用户, I want 学习者画像与教学日志自动维护、已掌握的概念不重教, so that 讲解越来越贴我
42. As a 用户, I want 自动档恒为普通一句话讲解（不弹教学页）, so that 我要的就是短
43. As a 管道/CI 用户, I want 非 TTY 时输出不带 ANSI 转义, so that 脚本能直接断言字符串

### 可读性契约

44. As a 用户, I want 每个断点选项都是"主体 —— 一句话解释"两段式, so that 我一眼看懂选什么、代价是什么
45. As a 用户, I want 提问主体加粗、解释缩进、选项编号, so that 长文案也能扫读
46. As a 用户, I want 推荐附一句话理由, so that 我不必自己推演选哪个

### demo 与报错

47. As a 用户, I want 文档完成后在断点被问"构建 demo / 自定义答案", so that 我可以止步于文档或继续
48. As a 用户, I want demo 生成到工作区并附运行指南, so that 我知道怎么亲手跑起来
49. As a 用户, I want 报错直接粘贴回 REPL 就能进入调试循环, so that 我不必人肉理解报错再转述
50. As a 用户, I want 报错回传由三层路由（斜杠→特征预筛→LLM 兜底）自动识别, so that 大多数时候我什么都不用记
51. As a 用户, I want 调试循环有 Max_loop=5 上限, so that 修不好时人工介入而不是无限烧 token

### 上下文工程体验

52. As a 长会话用户, I want 上下文占用到 80% 时自动压缩最老轮次, so that 会话理论上无限续航
53. As a 长会话用户, I want 最近 3 轮原文永不压缩, so that 工作记忆始终新鲜完整
54. As a 长会话用户, I want 压缩包（头部单包）带覆盖轮次目录, so that 压缩后溯源不断链
55. As a 用户, I want 错误猜想自动记入 Notepad, so that 关键教训不随压缩丢失
56. As a 用户, I want 工具列表按当前作用域裁剪, so that 模型专注且省 token
57. As a 用户, I want 手动 `/compact` 兜底, so that 我能主动管理上下文
58. As a 用户, I want 会话结束产出 final_report 入长期记忆, so that 下个项目能踩在上个项目的经验上

### 模型与账单

59. As a 用户, I want 用 DeepSeek 等 OpenAI 兼容端点, so that 我不被锁死在一家服务商
60. As a 用户, I want base_url 手填时少了 `https://` 也能跑, so that 少一个报错源
61. As a 用户, I want 本地 token 账单按角色聚合（输入/输出/总数）并落在项目目录, so that 隔离省 token 的设计被数据证明
62. As a 用户, I want 账单与内容都不外发云端, so that 隐私与主线设计不被观测工具干扰

### 安全与可观测

63. As a 用户, I want shell 命令过静态正则检查器（灾难删除/下载管道/凭证/git 不可逆）, so that 形态学危险操作被机械拦截
64. As a 用户, I want 白名单外命令按决策模式审批（AI 审核/逐条人工）, so that 打扰与安全由我平衡
65. As a 用户, I want 每条 deny/ask 落审计日志, so that 我能复盘 agent 都执行了什么
66. As a 用户, I want 密钥只存在本机 key 文件里、.gitignore 挡住所有密钥与本地状态, so that 我不会误把密钥推上远端
67. As a 用户, I want 应用绝不自动上报任何数据, so that 本地工具就是本地工具

### 交付

68. As a 用户, I want 文档构建完成时终检管线自动剥离全部【R#】标记, so that 交付物干净
69. As a 用户, I want 剥离前有快照备份、剥离后有确定性 diff 与语义校验, so that 剥离不误伤内容
70. As a 用户, I want 备份版和干净版两份都交给我, so that 我可以自己复核
71. As a 用户, I want 终检不过时回 builder 开新循环受 Max_loop 约束, so that 修复是系统性的且有上限
72. As a 用户, I want 交付物完整覆盖所选方式的文档集, so that 交付与承诺一致

### 外观（v2.0）

73. As a 用户, I want CLI 观感向 Claude Code 看齐（TS/Ink 前端）, so that 我用得顺手
74. As a 用户, I want 中文宽度按东亚字符宽度对齐, so that 表格与提示不错位
75. As a 用户, I want 前端只经协议消息与后端对话, so that 观感升级不牵动图与状态

## Implementation Decisions

### 总体架构（v2.0 双运行时）

- **双运行时（ADR-0005）**：TypeScript 前端（React 19 + Ink）负责观感/按键/渲染；Python 后端负责 REPL 宿主、主工作流图、旁路、账单。两者只经协议消息对话，前端不直接读写项目状态与 checkpointer。
- **现状标注**：已落地的是**纯 Python 单运行时 REPL**（ctx 与图全部在 Python 侧）；前端为已裁定未实现的目标形态，由 UX-2（协议服务化）与 UX-3（Ink 前端与打包）两票承接。
- **外观克隆的许可红线**：参考仓 `claude-code-best/claude-code`（逆向重实现）**无 License，即全权保留——只学架构模式，绝不复制代码**。Ink 用 npm 正版（MIT）。参考仓可学的模式：Bun≥1.3 构建、React 19、vendored ink fork 的取用方式、`src+components+screens+keybindings` 分区、marked+cli-highlight+chalk 的渲染分层、`get-east-asian-width` 处理 CJK 列宽（中文 UI 关键依赖）。
- **主工作流图为单一大图**（StateGraph + checkpointer）；AskAgent 为图外旁路 + 图内指引双通道（+ teach-me 深度形态）。
- **断点架构**：主图内零 interrupt()；每轮轮终即断点（state 落盘、控制权交还），用户自由 prompt 融合同 thread 续跑。等价于"正常 agent harness 的对话节律 + gate 变量确定性骨架"（ADR-0001）。
- **角色五件**：Builder（way2-4）/ way1 Actor（ReAct）/ DemoAgent / AskAgent（旁路 + 指引 + teach-me）/ verifier。GeneralAgent 已被 way1 吸收。
- **Actor 工厂**：4 构建方式 × 3 指引态（auto/ask/off；way1 恒 off）= 参数化一个工厂，图上不画平行路径。

### 运行时与配置（v1.8 真模型接线）

- **配置格式 = .env 平面（`~/.project-agent/config.env`）**：KEY=VALUE 逐行，零新解析依赖（PyYAML 被否，不进依赖树）；旧 `config.json` 首读自动迁移（读 → 写 .env → 删旧件，内容无损）。字段序即首启字段序：`main_model / api_key / base_url / sub_model / decision_mode`。
- **BOM 容错**：读侧剥 `\ufeff`（Windows PowerShell 管道/写盘常见伪影，不剥则首键名被污染、配置静默丢失）；问卷输入行同样剥。
- **配置全局、状态每项目**：配置在 `~/.project-agent/`（一次配置任何目录可用）；会话状态三件 `state.db / state.db.session.json / ledger.json` 落在 `<cwd>/.project-agent/`（换目录即新会话）。
- **OpenAI 兼容客户端**：ChatOpenAI 打 OpenAI 兼容端点（DeepSeek/官方皆可）；`base_url` 缺 scheme 时归一补 `https://`、去尾斜杠；`langchain_openai` **惰性导入**（模块导入零网络零重依赖，测试注入 chat 桩即零依赖跑协议面）；用量双路读取（`usage_metadata` 优先 → `response_metadata.token_usage` 兜底）。
- **运行时一站装配**：主/廉价客户端各包 MeteredModel 并**共享同一 TokenLedger**；`cheap = sub_model`（缺省同主模型，同一实例省一次构造；cheap 非 None 即挂压缩横切）；AskBypass 用独立 thread（`{thread_id}-ask` 后缀，ADR-0002 物理隔离）；`client_factory` 为注入缝（测试零网络全链路）。
- **接线效果**：verifier 环闭合、压缩横切四挂点亮、`/compact` 与 `/ask-for-help` 可用、账单落项目目录。
- **首启两层（v1.7 定形）**：
  - **应用级** = tkinter 配置窗口（主模型 / API key（掩码）/ base URL / 子模型 / **决策模式开关**（默认开=AI 自动审核）+ **测试连接按钮**）；窗口不可用、取消或异常 → 终端问卷 fallback（第五问：决策模式，回车默认 `ai_review`）。
  - **项目级** = build_ways 决议后的**单题**指引偏好一问；user_mode 由答案推导（auto/ask→novice、off→experienced）；`decision_mode` 来自配置窗口；`skill_packs` 由 REPL 种子注入默认 `["default"]`。
- **测试连接**：httpx POST `{base}/chat/completions`（`max_tokens: 1`，10s 超时），2xx 即通；**不阻塞保存**（key 好坏由用户自决）。httpx **惰性导入**（见"工程护栏"红线）。
- **密钥防推送**：`.gitignore` 覆盖 `.env`/`.env.*`/`*.env`/`config.json`/`ledger.json`/`state.db`/`state.db.session.json`/`.project-agent/`；冒烟产物 `BUILD_LOG.md`、`NOTES.md` 同样忽略（自托管冒烟曾误提交一例，已清除）。

### 图拓扑（相位图 —— 每轮 = 一个相位簇 + END）

一轮 = 一次 invoke（START→END）；**不存在"一轮跑完整个流程"**。START 挂**一条纯代码条件边**（`route_from_start → END_MAP`，一次路由覆盖全部相位入口），入口路由器择相位；相位节点算完写断点即回 END；跨轮由仪表盘重建位置。多数相位是单节点一簇，唯一的多节点簇是主环（assembler→actor→verifier→必要时 planner）。

| 相位节点 | 出口 |
|---|---|
| ask_tasks | END（写 `round`，简报直写零提问） |
| build_ways | 条件边：`build_way` 已设 → guidance_trigger；未设 → END（`choice:build_way`） |
| guidance_trigger | END（`question` 指引一问 / 或写映射后 `round`） |
| proposals（way4 三方案） | END（`choice:proposal`） |
| planner | END（todos 建立） |
| context_assembler → actor | actor → verifier（有模型）/ END（无模型骨架） |
| verifier | 条件边（计数最前）：计数=5 → loop_exhausted；todos 未清 → END（`round` 收轮）；todos 清但 task_complete 假 → planner（同轮重新规划）；双门通过 → END（双门成立后由**下一轮入口路由**接 docs_done，非本轮回边） |
| docs_done | 条件边：building → demo_agent；skipped/done → finalizer；未决 → END |
| demo_agent | 条件边：计数=5 → loop_exhausted；否则 → finalizer |
| finalizer → check_proper_output | 条件边：干净 → END（`finished`）；不干净且环<5 → planner；=5 → loop_exhausted |
| loop_exhausted | END（`loop_exhausted` 断点，交人工） |

- actor 节点内含 loop；way1 用 ReAct 循环，way2-4 用 grilling 循环。
- verifier 置位 gate 变量组：task_complete / is_docs_finished / output_clean / 环计数；条件边纯代码读 gate AND todos_all_completed。
- 图内唯一回边：verifier→planner（及 check→planner）。
- **可达路径必须写新断点**（01 冒烟钉板）：解释不了输入的节点也要写 fresh `round_end`，防 stale `turn_end_reason` 被重渲染。

### 状态契约（v1.1 增补：图状态设计）

**轮的机械化表述**（Q46 落地）：一轮 = 一次完整图执行（START→END）；断点 = END 时 `turn_end_reason` 落盘、checkpointer 持久化、控制权归 REPL。下一轮 invoke(同 thread) 由**入口路由器**（START 后第一组纯代码条件边）读仪表盘决定从哪个相位切入。仪表盘 = 相位状态机——"当前位置"不需要 mid-graph 挂起，全部由受控字段重建；这是"正常 agent 对话节律 + gate 确定性骨架"的合并形态。

**仪表盘字段表**（全局 state 只收以下受控字段，任何消息转储不得入内）：

| 字段 | 形状 | 写者 | 语义 |
|---|---|---|---|
| task_brief | str | ask_tasks | 任务简报，一次写定（= 用户开场第一句话） |
| build_way | way1–way4 | build_ways 决议轮 | 构建方式 |
| guidance_mode | auto/ask/off | guidance_trigger | AskAgent 指引三态（映射产物） |
| user_mode | experienced/novice | **guidance_trigger（v2.0：由指引答案推导）** | 编程基础语境（auto/ask→novice、off→experienced；不再单问） |
| guidance_pref | auto/ask/off | **guidance_trigger（question 答案轮）** | 指引偏好（映射输入；`off` 是合法已设值） |
| decision_mode | ai_review/manual | **配置窗口 → REPL 种子注入；`/mode` 可改** | 决策模式 = interrupt 旋钮初值 |
| skill_packs | list[str] | **REPL 种子注入默认 `["default"]`；`/skills` 可改** | 技能包选择 |
| proposal_set | list（≤3 方案摘要） | 三方案并行节点 | way4 专属 |
| selected_proposal | int | 选定轮 | way4 选定索引 |
| todos | list[{content, status 三态}] | planner 建 / actor 勾 | 工作流级计划，gate 判定对象（区别于 TodoWrite 私有面板与交付物 TODO.md——三个"todo"互不相同） |
| todos_all_completed | bool | 纯代码派生 | gate AND 的与项 |
| task_complete / is_docs_finished | bool | verifier | gate 变量 |
| output_clean | bool | check_proper_output | gate 变量 |
| 主环 / demo 环 / 终检环计数器 | int | 环回退自增；planner 开新循环清零 | 各环独立 Max_loop=5，互不污染 |
| demo_phase | undecided/building/skipped | docs_done 决议轮 | demo 阶段路由 |
| round_summary | str | actor 后置工序 | 最新轮摘要，指引注入材料 |
| notes_version | int 单调递增 | NotepadAdd 成功后自增 | Notepad 新鲜度 |
| round_count | int 单调递增 | actor 每产出一轮 +1 | 【R#】轮次编号源（也是 teach-me 页号） |
| compacted_rounds | list[(start,end)] | run_compression_check 追加 | 已压缩轮区间（溯源断链检测数据源） |
| guidance_read_version | int | AskAgent 消费后对齐 | 已读水位 |
| teach_me_pref | str（""\|"always"） | actor 起手四选决议（13 票） | "以后都深度教学"后每轮直接生成教学页 |
| current_scope | scope key | actor 声明、assembler 落定 | 规则文件 + 工具子集选择 |
| turn_end_reason | 枚举（见断点协议） | 产生断点的节点 | 断点协议主键 |
| turn_end_payload | 受控形状 | 同上 | REPL 渲染材料（问题文本/选项/交付概览） |
| awaiting_input_from | 角色标识 | 提问角色 | 下条自由 prompt 的融合目标 |
| final_report | str | finalizer | → Store 长期记忆 |

**私有 state key**（隔离红线的落点）：

| key | 归属 | reducer 语义 |
|---|---|---|
| actor_messages | 主线角色（way1–4 共用一条） | 追加；头部可驻留合并记忆区（头部单包，每包首行标覆盖轮次） |
| demo_messages | DemoAgent | 追加；报错回传融合于此 |
| assembled_context | Actor | 每轮整覆写——两段式的"装"半段 |
| resolution_inputs | 决议节点 | 无 reducer 整覆写：融合端按 reason 追加 `[*existing, text]`，决议节点消费后返回 `[]` 清空 |
| 旁路 AskAgent 独立 thread（`{thread_id}-ask`） | 图外，REPL 分发 | 追加，checkpointer 同机制，断点协议同构 |
| teach-me 调用 | 图内 actor 后置 / 起手，`role=ask_agent` | **无历史累积**：单发调用，历史不入任何 key |
| TodoWrite 私有三态面板 | 各角色 | 角色内部，不落盘不共享不经工具 |

图内 AskAgent 指引调用**无历史累积**：每次指引以当轮材料包（round_summary + 最新 NOTE + 文档切片）单发生成；指引文本呈现于用户侧，**绝不写入主线角色历史**——隔离红线在指引与 teach-me 通道同样生效（teach-me 产出的 HTML 由代码层写盘，不经模型工具调用）。

**节点读写表**（重要节点 state 契约）：

| 节点 | 读 | 写 |
|---|---|---|
| 入口路由器 | 全仪表盘 | 无（纯代码路由） |
| ask_tasks | 首条人类消息 | task_brief 一次写定 + round（14 票瘦身：四问循环删除，零 question） |
| build_ways | task_brief、user_mode（推荐语气） | choice 断点 payload；决议轮写 build_way |
| guidance_trigger | build_way、guidance_pref、上轮 question 答案 | 指引未答 → 发 question 断点；答案轮写 guidance_pref + user_mode 推导 + guidance_mode 映射 + round；已设 → 只写 guidance_mode |
| 配置条件边 | build_way × guidance_mode | 无——Actor 工厂参数每轮派生，不持久化 |
| 三方案并行 | 主线 grilling 历史 | proposal_set、choice 断点；选定轮写 selected_proposal |
| planner | task_brief、build_way/selected_proposal、交付物集定义 | todos（全 pending）、主环计数清零 |
| context_assembler | current_scope、rules 文件、todos 板、NOTES 切片（按 notes_version）、技能头、权限矩阵 | assembled_context、current_scope 落定；压缩检查（80% 阈值）可能产【R#-compact】 |
| actor | assembled_context（中间件送达）、私有历史、todos | 私有历史追加、todos 勾选、交付物落盘（带【R#】）、notes_version++、round_summary、turn_end_reason、current_scope 声明；**13 票**：起手消费上一轮指引四选（teach/teach_always/skip/brief）、后置 ask 档发指引 question 断点或直接 teach-me |
| verifier | 磁盘交付物、todos | task_complete、is_docs_finished（LLM 判内容） |
| docs_done | task_complete、is_docs_finished | 决议断点 payload；决议轮写 demo_phase |
| demo_actor | demo_messages（含融合的报错回传）、demo 文件 | demo_messages、demo 文件修复、demo 环计数 |
| finalizer | 全部交付物、会话产出 | final_report → Store |
| check_proper_output | 工作区全部文档 | output_clean、双份交付落盘；不过回 planner（终检环计数++） |

**入口路由真值表**（相位重建，纯代码——表驱动测试的直接素材；行序即优先级）：

| 仪表盘现状 | 本轮入口 |
|---|---|
| task_brief 未设 | ask_tasks |
| build_way 未设 | build_ways 决议 |
| guidance_pref 未设（None/""；**off 为合法已设**） | guidance_trigger（14 票新行：指引一问/答案消费） |
| way4 且 selected_proposal 未设且 todos 未设 | proposals（方案选定） |
| todos 为空 | planner |
| is_docs_finished=false 且 todos 未清 | context_assembler（主环） |
| todos 清且 task_complete=false | planner（重新规划，主环计数++） |
| **任一环计数≥5** | loop_exhausted 断点（demo 报错环封顶在此先行） |
| demo_phase=="building" 且 task_complete=true | demo_agent（报错回传环入口） |
| demo_phase=="skipped" 且 is_docs_finished=true | finalizer（12 票入口行 8） |
| 其余（task_complete=true 且 demo_phase 未设） | docs_done 决议（11 票改道） |

**断点协议**（turn_end_reason × payload × 融合目标——主接缝测试的断言对象）：

| turn_end_reason | 触发 | payload | 下条输入融合到 |
|---|---|---|---|
| round | actor 轮终（默认）；ask_tasks 简报；guidance_trigger 答案收轮 | 轮产出 + todo 板 | actor_messages |
| question | grilling 提问 / 指引偏好一问（guidance_trigger）/ ask 档指引询问（13 票四选含 teach-me） | 问题文本 + **解释** + 选项 + 提问角色 | awaiting_input_from 指向的私有 key |
| choice:build_way | build_ways | **解释** + 4 选项 + 推荐 + 一句话理由（≤20 字代码硬约束） | 决议节点写 build_way |
| choice:proposal | 三方案并行 | 3 方案摘要 | 决议节点写 selected_proposal |
| docs_done | task_complete=true 且 demo_phase 未设（入口路由接） | 交付概览 + demo?/自定义 | 决议节点写 demo_phase |
| loop_exhausted | 任一环计数=5 | 现场与求助说明 | 自由融合（人工接管） |
| finished | check_proper_output 通过 | 双份交付路径 | 终态；旁路问答通道仍可用 |

**统一输入协议**：所有断点输入都是自由文本。选择类断点同样吃自由文本（含序号），由对应决议节点解释——不存在结构化 resume 值。由此 **AskUserQuestion 实现为提问断点**（选项只作渲染辅助），不走工具内 interrupt——图内零 interrupt 的唯一例外维持为 shell 审批的 REPL 同步回调（不落 turn_end_reason、不进图）。代价：产生提问断点的节点必须可重入（提前返回后下轮重进不重复副作用）。

**"已设"判定规则（踩过三次的坑，升级为契约）**：仪表盘字段的"已设/未设"一律判 `value is not None and value != ""`——**不得用 truthy**。`skill_packs=[]`、`guidance_pref="off"`、`demo_phase` 语义都曾被 falsy 判定误伤（`off` 被当成未设会导致无限重问）。

**否定词优先序规则（同族第二坑）**："不需要"含子串"需要"、"生成不运行"含"不"、"暂不启用"含"启用"——所有关键词表**否定词必须前置**，单字否定用整串等值判定而非子串。

### 隔离与共享（ADR-0002）

- 各角色消息历史留私有 state key，永不进全局；全局 state（仪表盘）的字段清单与形状以"状态契约"节的**仪表盘字段表**为准，任何消息转储不得入内。
- 共享文档区 = 磁盘项目文档（带【R#】）+ NOTES.md；磁盘为事实来源（ADR-0004），Store 只承担 final_report 长期记忆（跨线程 KV）。
- 【R#】切片：ReadProjectDocs 按轮次前缀检索；NotepadRead 同套机制；每轮生成物全文落 BUILD_LOG.md。
- 版本号排序：notes_version（NotepadAdd 后自增）/ guidance_read_version（AskAgent 消费后对齐）；图内 guidance 通道入口检查版本差才注入；REPL 旁路直读磁盘天然最新。
- **旁路物理隔离**：AskBypass 用独立 thread（`{thread_id}-ask` + 独立 checkpointer 记录），与主线状态不共享。

### 上下文工程层

- **Assembler 两段式**：节点写 state（base prompt + 作用域规则 + todo 板 + notepad 切片 + 工具子集声明）→ actor 中间件送达（`@dynamic_prompt` 组 system / `wrap_model_call` override tools / before_agent 版本号检查）。理由：create_agent 构造期固定后唯一官方每轮变化通道。
- **摘要提炼（Q53=b）**：actor 节点内置后置工序——节点函数末尾、写 gate 前显式调用提炼函数，产出 round_summary + notes_version 自增。纯函数可单测。
- **压缩（Q54）**：模型调用前统一检查——所有 LLM 调用点（assembler / actor before_model / verifier / planner / demo_agent）挂同一压缩检查；80% 阈值触发，压最老 5 轮/包（便宜模型）为【R#-compact】摘要；压后目标 ≤60%，不足再压一包（同轮最多两包）；最近 3 轮原文永不压缩；错误猜想写 Notepad；手动 `/compact` 兜底（压缩批须随下轮 invoke 进图，否则 checkpointer 历史永不收缩——`add_messages` 指令批是收缩正道）。
- **注入位置（Q56）**：头部单包——全部压缩摘要合并为消息历史头部一个记忆区，每包首行标注覆盖轮次。
- **作用域**：规则文件（rules/src.md、rules/docs.md…）+ current_scope state 字段；工具子集 = 规则声明集 ∩ 静态矩阵；Todo 自动勾选沿用电三态。
- **技能懒加载**：上下文只注名字 + 一句话描述；SKILL.md 触发时才全文读入；推荐理由 ≤20 字代码硬约束。
- **final_report**：finalizer 产出 → Store 跨线程长期记忆 → 新会话 ask_tasks 时可检索注入（尚未接线，见"已知欠账"）。

### 指引与教学通道（13 票 + 14 票）

- **指引三态**：`auto` 每轮自动附普通讲解；`ask` 每轮发四选 question 断点；`off` 无指引轮。way1 恒 `off`（纯对话无构建轮可讲解）。
- **单题问卷（14 票）**：项目级只问 `guidance_pref` 一题，`QUESTIONNAIRE` 仅存该题；`user_mode` 由答案推导（auto/ask→novice、off→experienced）；`decision_mode` 在应用级配置窗口；`skill_packs` 由种子注入。
- **ask 档四选（13 票）**：`简短讲解 —— 一段话说明本轮要点` / `深度教学 —— 生成一页图文教学页（HTML，含可勾选的概念清单）` / `跳过 —— 这轮不需要讲解` / `以后都深度教学 —— 之后每轮自动生成教学页，不再询问`。
- **持久化**：选第 4 项写 `teach_me_pref="always"`；之后 ask 档直接生成教学页不再询问；`auto` 档恒普通讲解（用户裁定：要的就是短）。
- **选"简短讲解"的那一轮**当作已当场决定"要讲解"——走 auto 同款普通指引，**不再重问**（`guidance_ask_consumed` 局部标志）。
- **teach-me 生成契约**：`role=ask_agent` 单发调用（无历史累积）；prompt = 技能全文 + 本轮摘要 + 文档切片 + 学习者画像 + 既往教学日志（"已掌握的概念不要重教"）；模型返回 HTML 全文，**由代码层写盘**（不经模型工具调用——工具执行回路仍属欠账）。
- **落盘三件**（`teach-me/`）：`R{n}/index.html`（自包含单文件：内联 CSS、零外链、零 JS 依赖；概念清单每项带 checkbox，勾选状态存 `localStorage`，key=`teach-me-R{n}`；中文排版；页首标轮次与日期）、`learner-profile.md`（纯代码维护的画像）、`session.md`（纯代码维护的教学日志）。写盘经 `SharedDocs.write_any` 路径防护（拒 `..`，与 DemoAgent 同法）。
- **回执**：round_output 只渲染一行 `教学页已生成：teach-me/R{n}/index.html`，不贴 HTML 全文。
- **解释引擎**：序号优先（裸/语境正则），关键词次之；teach-me 的"以后"类持久词先于单轮词判定（防"以后都深度教学"被吞成单轮）。

### 文案可读性契约（13 票钉板）

- **全量提问与选项一律两段式**：`主体 —— 一句话解释`（全角破折号）。解释说明"选它的后果/代价"，不是复述主体。
- **payload 强制**：`question` 与 `choice:build_way` 的必填字段含 `explanation`（缺则 `PayloadError`）。
- **三层渲染**（纯函数）：第一行加粗问题主体 → 解释缩进两级 → 选项逐行编号（主体加粗、说明不加粗）→ 提问者行。
- **TTY 退化**：加粗等 ANSI 只在交互 TTY 生效；管道/重定向退化为纯文本——输出被日志收集时不带转义污染，脚本可直接比字符串。
- **推荐必附理由**：构建方式推荐 = 模型实时推荐 + 一句话理由（≤20 字，代码截断），模型不可用则静态兜底。
- **文案即契约的边界**：断言"主体"子串而非整句（避免文案微调打碎测试），但主体文本本身逐字钉死在票面。

### 工具权限

- **矩阵（代码层强制，构造期预注册）**：Builder/DemoAgent/way1 Actor = 全工具；AskAgent = 只读（FileRead/Glob/Grep/ReadProjectDocs/NotepadRead）+ 联网（WebSearch/WebFetch）+ 提问（AskUserQuestion）+ SkillRecommend + NotepadAdd；交付物 TODO.md 写权 Builder 独占。
- **shell 权限**：静态正则检查器（8 类形态学：灾难删除/下载即执行/提权/凭证面/git 不可逆/网络出口/重定向/命令替换——独立于白名单、deny 全档生效、allow 命中也拦）+ 两旋钮（boundary: readonly/project-write/full 仅 flag × interrupt: AI 审核/全权人工/yolo 仅 flag；决策模式 = interrupt 初值）+ 复合命令拆段 + wrapper 剥离 + 解析失败=ask（fail-closed）。Windows：`rm` 与 `Remove-Item` 别名都拦。
- **DemoAgent 不运行 demo（ADR-0003）**：工具面 = 全工具，shell 仍过静态正则+两旋钮；唯运行类命令在权限层拒绝，运行权在用户；报错回传融合进 demo_messages，↺环受 demo 环计数约束。
- **排除工具**：AgentTool / SkillTool / Plan Mode 两件 / Task* 六件 / SendMessage / NotebookEdit / MCP / LSP（v2+）。
- **欠账**：工具**执行回路**尚未实现——actor 目前以文本指令桥（`写入：`、`记录：`）落盘，无真实工具调用环。见"已知欠账"。

### 外观与分发（v2.0 UX 裁定）

- **前端**：TypeScript + React 19 + Ink；观感对齐 Claude Code（信息层次、按键提示、面板折叠）；中文列宽按东亚字符宽度计算（`get-east-asian-width`）。
- **后端**：Python（现有全部模块）；对外暴露的交互面从"终端 stdin/stdout"升级为"协议消息流"（UX-2 票）；前端只消费消息与发送输入，不持有业务状态。
- **许可红线**：无 License 仓只学模式不抄代码（详见"总体架构"）；引入的前端依赖必须是 MIT/Apache 等宽松许可。
- **tkinter 的边界**：仅用于首启配置窗口（"Windows 观感"就这一处）；CLI 本体不走 tkinter。
- **命令与分发**：`[project.scripts]` 只留 `engine`（旧名 `project-agent` 废弃，无外部用户）；`pipx install` 分发；`argparse(prog="engine")`。
- **仓库与许可**：远端 `https://github.com/Iivresse1/engine_agent.git`；项目自身以 **Apache-2.0** 发布（远端已有 LICENSE）。集成分支 `integration/project-agent`，收口后并入 `main`。
- **兼容降级**：无显示环境 / 无 tkinter / 用户取消 → 一律退终端问卷；前端未接线时后端仍可裸终端运行（现状即此形态）。

### 协议消息层（UX-2 契约，v2.1）

前后端唯一主接缝（ADR-0005 接缝预算：这是**新增的唯一一条**）。方向只有两个：下行（后端→前端，展示）与上行（前端→后端，输入）。**业务状态全部留在后端**——前端不持有 Dashboard、不解析决议、不做路由：[前端拿到 `round_end` 只负责"画"，拿到用户按键只负责发 `input`]。

**消息表**（表即契约，与断点协议同等级；字段即形状，缺/多均 `MessageError`）：

| 方向 | type | 字段 | 语义 |
|---|---|---|---|
| down | ready | banner, opening_prompt | 会话就绪：横幅 + 开场提示语 |
| down | prompt | awaiting | 请求输入；awaiting = `awaiting_input_from`（无则 `""`） |
| down | round_end | reason, payload, lines | 断点交付；lines 为终端降级渲染行（前端可直绘） |
| down | notice | text | 即时提示（命令回执 / `/status` / 错误文案） |
| down | teach_page | path, round | 教学页已生成（前端可打开） |
| down | farewell | text | 会话终止（`/exit`、EOF、终态） |
| up | input | text | 一条自由文本（含斜杠命令原文，由后端分发） |
| up | quit | （无） | 请求退出（后端回 `farewell`） |

**四条硬约束**：

1. **信封只一层**：编码结果即 `{"type": "<type>", ...字段}`，无嵌套 envelope、无版本协商字段。解码校验 `type` 在一次查表内完成。
2. **后端仍需裸终端可用**：`default_rendering(kind, payload)` 是纯函数，把任意下行消息折成终端行（`ready`→两行、`round_end`→`断点 · {reason}` + 载荷逐行、`prompt`→空、`notice`→text、`teach_page`→`教学页已生成：{path}`、`farewell`→text）。前端未接线时 REPL 走此路径，行为与 v2.0 一致（这就是"兼容降级"的落地形态）。
3. **零业务逻辑在协议层**：`messages.py` 只做形状校验与折叠渲染，不 import 任何图/节点/模型模块（红线：协议层反向依赖图 = 倒退）。
4. **结构化语义仍走自由文本**：决议类断点的 `payload` 原样透传（前端不得解释），`input` 永远是纯文本——与"统一输入协议 / 图内零 interrupt"一致。

**尚未落地的部分**（记入"已知欠账"）：WebSocket 传输、后端服务化进程模型、前端 Ink 组件、Bun 打包。

### 路由

- **REPL 混合路由三层**：斜杠命令（前缀匹配，零 LLM）→ 报错特征规则预筛（Traceback/Error: 等 + demo 阶段活跃）→ LLM 窄分类兜底（只判"报错回传 vs 普通输入"）。
- **斜杠命令**：`/help /status /compact /ask-for-help /skills /mode /exit`（前缀匹配，按长度降序取最长命中）。
- **首启两层**：见"运行时与配置"节（应用级=配置窗口 + 终端 fallback；项目级=单题指引偏好）。
- **开场序列**：banner（`Project Agent。输入 /help 查看命令。`）→ 空行 → `今天要做什么呢？` → 用户首条自由文本即图输入。

### 工程护栏（Q63 环境改进）

- **测试零警告**：pytest `filterwarnings = ["error"]`，602 条警告治本清零（不设 ignore）。
- **langgraph 注解钉板**：节点 `config` 注解必须写 `Optional[RunnableConfig]`——langgraph 1.2.17 签名白名单只认 `typing.Optional` 形式，PEP 604 `| None` 既触发 UserWarning 又让 config 注入失效。
- **ruff 窄规则集**：`E4/E7/E9/F/W/I`（风格偏好项 UP/SIM/BLE 不进检查）；tests 放宽 F841。
- **pre-commit**：`.githooks/pre-commit` 跑 ruff + 全量 pytest，钉 `.venv` 解释器（经 `core.hooksPath` 接线；仓库 `.venv` 是唯一可跑环境）。
- **术语哨兵**：`tests/test_glossary_sentinel.py` 用 AST 拆词对 GLOSSARY `_Avoid_` 单词子集机械强制；裁定术语走豁免清单并写理由。
- **Q39 红线（精化后）**：不自动上报任何数据 + **主包顶层不 import 网络库**（gui_config 的 httpx 必须函数内惰性导入，配"顶层 import 即倒退"哨兵测试）。
- **契约对账**：Dashboard 字段 / 入口路由真值表改动必须回填 spec 并同步契约测试——表与代码不一致 = 票未收口。
- **红绿双向**：每个 bug 修复先造红再转绿；冒烟测试是运行时行为的权威。
- **文档先行（Q68 新纪律）**：新裁定先入 spec / GLOSSARY 再开票——票面只做"由 spec 到代码"的翻译，不做新设计。

### 模型与版本

- 主角色/子角色各自可配模型+key（可同 key）；压缩/摘要/窄分类走子档便宜模型。
- 版本钉（实测）：langgraph 1.2.17 / langchain 1.4.7 / langchain-core 1.7.0 / langchain-openai 1.7.2 / pytest 9.1.1；Python 3.12。
- 依赖：`langgraph>=1.2`、`langchain>=1.3.x`、`langchain-openai>=1.0`（传递带入 openai SDK）。
- 防雷：`modify_state_before_agent` 不存在（社区讹传）；middleware 细节 API 演进快，锁定小版本验证签名。

### 可观测

- 本地 token 账单：usage_metadata 按 thread/角色聚合（输入/输出/总数），落 `<cwd>/.project-agent/ledger.json`；**不上报、不引入 LangSmith**。
- shell 审计日志：规则 id + 命令段 + 原因码（deny/ask 判决时刻落账）。

## Testing Decisions

**测试哲学**：只测外部行为——"输入文本 → 可观察的轮终 state + 终端输出"，不测内部实现细节。接缝已与用户确认：

- **主接缝 = REPL↔主图协议**：`invoke(user_prompt) → 轮终 state`。该协议有具体契约：**断点协议表 + 仪表盘字段表 + 入口路由真值表就是测试的断言对象**——回放脚本逐轮断言 turn_end_reason / turn_end_payload / 融合后目标 key 的变化；真值表逐行展开为表驱动相位重建测试。用可编程假模型 + 临时工作区回放完整会话（开场 → 简报 → 方式 → 指引一问 → 答案 → 主环 → 断点续跑 / 报错回传 / 压缩触发）。checkpointer 天然支持会话回放式测试。
- **新接缝预算（v2.0）**：前端引入**只新增一个**主接缝（前端↔后端协议消息，UX-2 定义）；后端↔图的主接缝不变。不新增别的缝。
- **LLM 边界**：假模型按脚本出牌，验证路由逻辑零真模型。
- **工具边界**：假 shell（记录调用+预置输出），验证权限矩阵 / 静态正则拦截 / 两旋钮。
- **磁盘边界**：tmp 工作区测【R#】写入剥离 / Notepad 版本号 / 终检 diff / teach-me 三件落盘。

**测试代码与主项目物理分隔**（v1.1 钉板，仍有测试守护）：

- 主项目采用 src 布局（单一主包）；测试树为独立顶层目录，两者互不嵌套。
- 运行依赖与测试依赖分组；测试依赖走可选依赖组（extras）。
- 零反向依赖：主包不 import 测试树任何内容。
- 测试替身（可编程假模型、假 shell、会话回放脚本）全部住测试树，不随主包分发。
- 测试运行配置独立于应用运行时配置。

**v1.8 / v2.0 新增可测面**（全部为可注入桩的纯层）：

| 面 | 测法 |
|---|---|
| 配置格式 | `parse_env` / `render_env` 纯函数往返；旧 json 迁移；BOM 剥离；decision_mode 受控归一与旧文件向后兼容 |
| 配置窗口 | 纯函数 `form_fields_to_config`（必填校验/归一）+ `test_connection(transport=MockTransport)` 零网络；tkinter 壳不单测，只测"不可用即 fallback"路径 |
| 模型客户端 | `OpenAICompatClient(chat=桩)` 零网络；`normalize_base_url` 边界；usage 双路读取 |
| 运行时装配 | `build_model_runtime(client_factory=桩)` 断言共享账单、cheap 缺省同主、AskBypass thread 后缀 |
| 断点渲染 | `render_question_payload(payload, ansi=True/False)` 纯函数断言两层输出（带/不带 ANSI） |
| 指引与教学 | `interpret_teach_choice` 纯函数（含"以后都"不被吞）；`run_teach_me` 用假模型断言 prompt 含技能全文/画像/日志、三件落盘、回执行 |
| 续跑回灌 | 跨进程 `_seed_state_from_checkpoint`：桩 app 带 `get_state` 与不带两路；红绿双向验证 |
| 协议消息层 | `encode`/`decode` 纯函数往返（缺字段/多字段/错类型各造红）；`default_rendering` 六类下行逐行断言；红线哨兵：`messages.py` 不得 import 图/节点/模型模块 |
| 红线哨兵 | 主包顶层禁网络库 import（新增"顶层 import 即倒退"）+ 不外发数据；术语哨兵 |

**重点测什么**（对应架构红线）：断点续跑的 state 融合正确性（按断点协议表逐行）；隔离红线（角色 A 的历史绝不出现于角色 B 的输入，指引与 teach-me 通道同样受测）；gate AND todos 判定矩阵与入口路由真值表（多分支表驱动）；压缩边界（80% 触发 / 3 轮保护 / 水位 60% / 两包上限）；静态正则的 8 类拦截；终检管线的"零残留+零误伤"；版本号排序的 stale-read 杜绝；**falsy 与子串两个陷阱家族各留回归哨兵**。

## 已知欠账（设计已定、实现未落地）

> 记账用途：这些不是缺陷也不是新设计，是"票还没开"的差额。spec 与代码的不一致只允许出现在此处。

| 欠账 | 现状 | 归属 |
|---|---|---|
| 工具执行回路 | actor 只发文本指令桥（`写入：`/`记录：`），无真实工具调用环——`<Shell>/<Glob>/<FileRead>/<DocScaffold>/<AskUserQuestion>` 尚未执行 | 工具票 |
| decision_mode / skill_packs 图内消费者 | 字段有写入（配置窗口/种子注入），图内零消费（shell 审批档位接线未接） | 权限接线票 |
| AskUserQuestion 工具本体 | 仅协议级"提问断点"语义，无工具实现 | 工具票 |
| TodoWrite 私有面板 key | 概念在（各角色私有），state 里无对应 key | 工具票 |
| 旁路 checkpointer 持久化 | AskBypass 有独立 thread，但历史未落盘（重启即失） | 旁路票 |
| current_scope 写者 | assembler 落定，actor 声明未实现 | 作用域票 |
| verify_link 接入指引 | 指引里的文档链接未做抓取验证（用户故事 36 未满足） | 指引票 |
| final_report 检索注入 | finalizer 产出 final_report，ask_tasks 未做检索注入 | 记忆票 |
| ask 档普通讲解的循环 | 指引四选已真断点化，但"讲什么"的内容循环仍单发 | 指引票 |
| 压缩挂点补全 | finalizer / 旁路 / 指引三条 LLM 路径未挂压缩检查 | 压缩票 |
| 官方 LangGraph Store | 只有 InMemory 轻实现，跨会话长期记忆不可用（ADR-0004 已记原因） | 记忆票 |
| 前端传输层（UX-2 余下） | 协议消息表与纯翻译层已落 `messages.py`（v2.1）；WebSocket 传输、后端服务化进程模型未做 | UX 票 |
| 前端界面（UX-3） | Ink/React 19 组件、按键、Bun 打包未开票 | UX 票 |
| guidance_read_version 门归属 | assembler 先消费 vs 指引通道自消费，未终裁 | 待裁 |
| planner 模板覆盖修复 todo | 终检环回 planner 会覆盖修复项，持久化未定 | 待裁 |
| nodes.py 相位拆分 | 单文件 1700+ 行，docstring 导航已加，物理拆分未做 | 待裁 |

## Out of Scope

- OS 级沙箱（容器/landlock）——v2+，v1 逻辑隔离已覆盖
- demo 自动运行 / 冒烟 / 自愈循环——ADR-0003 明确运行权在用户
- LangSmith / 云端观测——已钉不引入
- 报错回传的启发式检测——第三层 LLM 兜底已覆盖
- 余弦相似度 / 语义检索——v1 关键词 +【R#】前缀够用，接口留 query 参数不堵路
- MCP / LSP / NotebookEdit / Task 系后台工具——v2+ 扩展点
- 新手强引导机制的进一步细化（用户自留）
- yolo / boundary=full 档的实际使用（仅保留 flag 定义）
- 浏览器 Web UI / 多用户服务化 / 远程托管——前端限本机终端（v2.0 只把"终端观感"升级为 Ink，**不是** Web 化）
- ~~Web UI / Studio / 前端——已砍（v1 全 CLI）~~ → **v2.0 作废**：终端前端纳入范围（ADR-0005）
- ~~CLI 视觉美化方案（rich/textual 选型 = Q15 后置）~~ → **v2.0 作废**：已改为 Ink/React 方案，rich/textual 不再考虑

## Further Notes

- 决策全量台账：`.scratch/project-agent/decisions.md`（Q1–Q68，含演化痕迹与否定记录）
- 研究笔记：`docs/research/langgraph-verification-2026.md`（LangGraph 1.x 事实核查）、`docs/research/shell-permission-survey.md`（8 产品权限调研）
- 版本敏感警告集中在台账"middleware 事实核查"节——实现前先在锁定版本上验证 `request.override` / `dynamic_prompt` 签名；"END 后同 thread 再 invoke 从 START 重跑且 state 恢复"已实测通过（轮协议的底层前提成立）。
- v1.1 的推导性决策现已全部落地或转入欠账清单：`turn_end_payload` / `awaiting_input_from` / 环计数器分字段 / `demo_phase` 均已实现；`AskUserQuestion = 提问断点` 仍是协议语义（工具本体欠账）；图内指引无历史累积已由 teach-me 通道一并继承。
- **文档纪律（Q68）**：spec 是唯一权威。代码与 spec 表不一致 = 缺陷（除非记在"已知欠账"）；新裁定先写进 spec 再开票，避免"文档没动就开工"。
- 里程碑顺序（历史）：REPL 壳+图骨架（断点跑通）→ 工具层+矩阵 → 上下文工程层 → 终检管线 → 账单 → 真模型接线 → 问卷重编排/外观。此顺序让隔离红线和断点这两个最难对的东西最早被验证。
