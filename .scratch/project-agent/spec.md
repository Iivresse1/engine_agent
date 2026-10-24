# Spec: 项目构建 Agent（Project Agent）v1.1

Status: ready-for-agent
发布: 2026-10-24（v1）；v1.1 增补：图状态契约 / 断点协议 / 测试与主项目分隔（同日）
来源: 32 轮 grilling 设计会话（决策台账 .scratch/project-agent/decisions.md，47+ 决策）
词汇: 严格使用 GLOSSARY.md；遵循 docs/adr/0001–0004

## Problem Statement

用户有一个项目想法，但不知道怎么把它变成一个结构清晰的项目。直接让通用 AI 助手帮忙，得到的是一次性、无法沉淀的对话——聊天记录越滚越长，AI 忘了最初的目标，用户也没学到东西；想边构建边问"为什么用这个技术栈"，只会让构建用的上下文越来越臃肿，token 花在重复搬运历史上。

同时，经验丰富的开发者和零基础的用户需要的是完全不同的构建体验：前者要快、要少打扰；后者要每一步都有人解释"为什么这么做"。

## Solution

一个本地 CLI 应用：用户丢进一个想法，通过分档的构建方式（从纯对话到完整项目文档）增量构建出项目文档包，期间可以随时旁路提问学习技术知识——问答与构建共享同一份磁盘文档但对话上下文完全隔离，构建不被提问拖慢，提问不被构建污染。

构建全程以轮次为节律：每轮结束交还控制权（断点），用户自由输入融合续跑。构建方式分四档，新手可以开启"每轮构建指引"边构建边学。文档完成后可指令生成可运行 demo（生成不运行，报错由用户粘贴回来、agent 诊断）。上下文工程层（组装/压缩/Notepad/作用域）保证长会话不退化。

## User Stories

### 入口与首启

1. As a 用户, I want 首次启动只被问一次模型和 API 配置, so that 我不用每次启动都重复设置
2. As a 用户, I want 之后每次启动直接进入会话零提问, so that 我可以立即开始工作
3. As a 用户, I want 用 `/mode`、`/skills` 等斜杠命令随时修改配置, so that 不用重启就能调整
4. As a 有编程基础的用户, I want 默认进入简洁高效的构建流程, so that 少打扰快出活
5. As a 零基础用户, I want 被问"有一定编程基础 / 我不了解编程", so that 我能选到适合自己的构建体验
6. As a 零基础用户, I want 选"不了解编程"后自动获得每轮构建指引, so that 我能边构建边理解发生了什么
7. As a 半懂用户, I want 新手指引做成三态开关（自动每轮/每轮询问/关）, so that 我能按需调节被打扰的程度
8. As a 用户, I want 第一次进入项目工作流时才被问构建偏好（模式/指引/决策模式/技能包）, so that 这些项目级选择出现在语义就近的地方

### 构建方式

9. As a 用户, I want 被问"你想做什么"（ask_tasks）, so that agent 知道我的任务
10. As a 用户, I want 四种构建方式（对话/轻 grill/简化文档/完整文档）带推荐和一句话理由, so that 我能快速选对深度
11. As a 只想聊天的用户, I want 选对话方式后得到 ReAct 循环的普通 agent 体验, so that 小事不必走流程
12. As a 做小脚本的用户, I want 轻方式（IDEA.md 一页纸 + 短 grilling 直达 demo）, so that 轻活不被文档拖慢
13. As a 做个人作品的用户, I want 简化文档集（README+TODO+目录树）, so that 有沉淀但不臃肿
14. As a 做复杂工程的用户, I want 完整文档框架, so that 项目有工程级的纸面基础
15. As a 做复杂工程的用户, I want grilling 到位后并行看到三套构建方案, so that 我能对比技术栈与复杂度取舍
16. As a 做复杂工程的用户, I want 断点处自由选定或融合方案, so that 我不被锁死在单一预设里

### 构建过程

17. As a 用户, I want 构建以轮次为节律、每轮结束交还控制权, so that 我随时可以插话改变方向
18. As a 用户, I want planner 先列出 todo 清单, so that 构建有可见的计划而非黑箱
19. As a 用户, I want todo 清单三态显示（未开始/进行中/完成）, so that 我随时知道进度和当前焦点
20. As a 用户, I want 每轮生成物带【R#】轮次标记, so that 我知道什么是什么时候产生的
21. As a 用户, I want 主角色按项目阶段推荐技能（指令+20字内理由）, so that 我知道下一步可以调什么
22. As a 用户, I want 技能推荐不打断我（AI 审核档）或每条都暂停等我确认（人工裁决档）, so that 打扰程度由我定
23. As a 用户, I want 复杂文档由框架先行、grilling 指引逐步填写, so that 文档不是一次性倒出来而是长出来的

### 学习与提问（旁路）

24. As a 用户, I want `/ask-for-help` 随时切换到旁路问答, so that 疑问不打断构建主线
25. As a 用户, I want 旁路问答读的是项目文档切片而非主对话历史, so that 问"为什么选X"能得到项目语境的答案
26. As a 用户, I want 旁路问答自己的历史独立累积, so that 追问不丢、上下文不串
27. As a 新手用户, I want 每轮构建指引附"为什么这么做+下一步+技术栈文档链接", so that 我在构建中同步学习
28. As a 新手用户, I want 指引在我读完主产出的侧栏位置出现, so that 学习不遮挡构建本身
29. As a 想深入的用户, I want 文档链接经过抓取验证有效, so that 我不被死链浪费

### demo 与报错

30. As a 用户, I want 文档完成后在断点被问"构建 demo / 自定义答案", so that 我可以止步于文档或继续
31. As a 用户, I want demo 生成到工作区并附运行指南, so that 我知道怎么亲手跑起来
32. As a 用户, I want 报错直接粘贴回 REPL 就能进入调试循环, so that 我不必人肉理解报错再转述
33. As a 用户, I want 报错回传由三层路由（斜杠→特征预筛→LLM 兜底）自动识别, so that 大多数时候我什么都不用记
34. As a 用户, I want 调试循环有 Max_loop=5 上限, so that 修不好时人工介入而不是无限烧 token

### 上下文工程体验

35. As a 长会话用户, I want 上下文占用到 80% 时自动压缩最老轮次, so that 会话理论上无限续航
36. As a 长会话用户, I want 最近 3 轮原文永不压缩, so that 工作记忆始终新鲜完整
37. As a 长会话用户, I want 压缩包（头部单包）带覆盖轮次目录, so that 压缩后溯源不断链
38. As a 用户, I want 错误猜想自动记入 Notepad, so that 关键教训不随压缩丢失
39. As a 用户, I want 工具列表按当前作用域裁剪, so that 模型专注且省 token
40. As a 用户, I want 手动 `/compact` 兜底, so that 我能主动管理上下文
41. As a 用户, I want 会话结束产出 final_report 入长期记忆, so that 下个项目能踩在上个项目的经验上

### 安全与可观测

42. As a 用户, I want shell 命令过静态正则检查器（灾难删除/下载管道/凭证/git 不可逆）, so that 形态学危险操作被机械拦截
43. As a 用户, I want 白名单外命令按决策模式审批（AI 审核/逐条人工）, so that 打扰与安全由我平衡
44. As a 用户, I want 每条 deny/ask 落审计日志, so that 我能复盘 agent 都执行了什么
45. As a 用户, I want 本地 token 账单按角色聚合（输入/输出/总数）, so that 隔离省 token 的设计被数据证明
46. As a 用户, I want 账单不外发云端, so that 隐私与主线设计不被观测工具干扰

### 交付

47. As a 用户, I want 文档构建完成时终检管线自动剥离全部【R#】标记, so that 交付物干净
48. As a 用户, I want 剥离前有快照备份、剥离后有确定性 diff 与语义校验, so that 剥离不误伤内容
49. As a 用户, I want 备份版和干净版两份都交给我, so that 我可以自己复核
50. As a 用户, I want 终检不过时回 builder 开新循环（而非打补丁）受 Max_loop 约束, so that 修复是系统性的且有上限
51. As a 用户, I want 交付物完整覆盖所选方式的文档集, so that 交付与承诺一致

## Implementation Decisions

### 总体架构

- **REPL 宿主 + 主工作流图 + 旁路**：REPL 负责终端 I/O、斜杠路由、混合路由三层、断点持有、shell 审批同步回调、本地账单；主工作流图为单一大图（StateGraph + checkpointer）；AskAgent 为图外旁路 + 图内新手指引双通道
- **断点架构**：主图内零 interrupt()；每轮轮终即断点（state 落盘、控制权交还），用户自由 prompt 融合同 thread 续跑。等价于"正常 agent harness 的对话节律 + gate 变量确定性骨架"
- **角色五件**：Builder（way2-4）/ way1 Actor（ReAct）/ DemoAgent / AskAgent（旁路+指引）/ verifier。GeneralAgent 已被 way1 吸收
- **Actor 工厂**：4 构建方式 × 2 指引开关 = 8 配置参数化一个工厂，图上不画平行路径

### 图拓扑（节点序）

start → ask_tasks → build_ways → guidance_trigger → conditional_edge（8 配置）→ [way4: 三方案并行→断点选定] → planner → context_assembler + actor（内含 loop）→ verifier → conditional_edge（gate AND todos_all_completed）→ [way3/4: is_docs_finished→断点"文档完成"→demo_actor（↺报错回传环）] → finalizer → check_proper_output → FINISH

- context_assembler 为图内显式节点，位于 loop 头部，每轮跑
- actor 节点内含 loop；way1 用 ReAct 循环，way2-4 用 grilling 循环
- verifier 置位 gate 变量组：task_complete / is_docs_finished / output_clean / loop_count；条件边纯代码读 gate AND todos_all_completed（todo 全清为纯代码判定）
- todos 未清回 actor；todos 清但 gate 未过回 planner（重新规划）；loop_count=5 断点求助
- check_proper_output：LLM 检测标记→快照备份→正则移除→确定性 diff 校验→LLM 语义校验→双份交付；不过回 planner 开新循环（≤5）

### 隔离与共享（ADR-0002）

- 各角色消息历史留私有 state key，永不进全局；全局 state（仪表盘）的字段清单与形状以"状态契约"节的**仪表盘字段表**为准（v1.1 唯一权威版），任何消息转储不得入内
- 共享文档区 = 磁盘项目文档（带【R#】）+ NOTES.md；磁盘为事实来源（ADR-0004），Store 只承担 final_report 长期记忆（跨线程 KV）
- 【R#】切片：ReadProjectDocs 按轮次前缀检索；NotepadRead 同套机制
- 版本号排序：notes_version（NotepadAdd 后自增）/ guidance_read_version（AskAgent 消费后对齐）；图内 guidance 通道入口检查版本差才注入；REPL 旁路直读磁盘天然最新

### 状态契约（v1.1 增补：图状态设计）

**轮的机械化表述**（Q46 落地）：一轮 = 一次完整图执行（START→END）；断点 = END 时 `turn_end_reason` 落盘、checkpointer 持久化、控制权归 REPL。下一轮 invoke(同 thread) 由**入口路由器**（START 后第一组纯代码条件边）读仪表盘决定从哪个阶段切入。仪表盘 = 相位状态机——"当前位置"不需要 mid-graph 挂起，全部由受控字段重建；这是"正常 agent 对话节律 + gate 确定性骨架"的合并形态。

**仪表盘字段表**（全局 state 只收以下受控字段，任何消息转储不得入内）：

| 字段 | 形状 | 写者 | 语义 |
|---|---|---|---|
| task_brief | str | ask_tasks | 任务简报，一次写定 |
| build_way | way1–way4 | build_ways 决议轮 | 构建方式 |
| guidance_mode | auto/ask/off | guidance_trigger | AskAgent 指引三态 |
| proposal_set | list（≤3 方案摘要） | 三方案并行节点 | way4 专属 |
| selected_proposal | int | 选定轮 | way4 选定索引 |
| todos | list[{content, status 三态}] | planner 建 / actor 勾 | 工作流级计划，gate 判定对象（区别于 TodoWrite 工具私有面板与交付物 TODO.md——三个"todo"互不相同） |
| todos_all_completed | bool | 纯代码派生 | gate AND 的与项 |
| task_complete / is_docs_finished | bool | verifier | gate 变量 |
| output_clean | bool | check_proper_output | gate 变量 |
| 主环 / demo 环 / 终检环计数器 | int | 环回退自增；planner 开新循环清零 | 各环独立 Max_loop=5，互不污染 |
| demo_phase | undecided/building/skipped | docs_done 决议轮 | demo 阶段路由 |
| round_summary | str | actor 后置工序 | 最新轮摘要，指引注入材料 |
| notes_version | int 单调递增 | NotepadAdd 成功后自增 | Notepad 新鲜度 |
| guidance_read_version | int | AskAgent 消费后对齐 | 已读水位 |
| current_scope | scope key | actor 声明、assembler 落定 | 规则文件 + 工具子集选择 |
| turn_end_reason | 枚举（见断点协议） | 产生断点的节点 | 断点协议主键 |
| turn_end_payload | 受控形状 | 同上 | REPL 渲染材料（问题文本/选项/交付概览） |
| awaiting_input_from | 角色标识 | 提问角色 | 下条自由 prompt 的融合目标 |
| final_report | str | finalizer | → Store 长期记忆 |

**私有 state key**（隔离红线的落点）：

| key | 归属 | reducer 语义 |
|---|---|---|
| actor_messages | 主线角色（way1–4 共用一条） | 追加；头部可驻留合并记忆区（头部单包，每包首行标覆盖轮次） |
| demo_messages | DemoAgent | 追加；报错回传融合于此（v1 的"独立 thread"表述被 v2 单图吸收） |
| assembled_context | Actor | 每轮整覆写——两段式的"装"半段 |
| 旁路 AskAgent 独立 thread | 图外，REPL 分发 | 追加，checkpointer 同机制，断点协议同构 |
| TodoWrite 私有三态面板 | 各角色 | 角色内部，不落盘不共享不经工具 |

图内 AskAgent 指引调用**无历史累积**：每次指引以当轮材料包（round_summary + 最新 NOTE + 文档切片）单发生成；指引文本呈现于用户侧栏，**绝不写入主线角色历史**——隔离红线在指引通道同样生效。

**节点读写表**（重要节点 state 契约）：

| 节点 | 读 | 写 |
|---|---|---|
| 入口路由器 | 全仪表盘 | 无（纯代码路由） |
| ask_tasks | — | task_brief；question 断点 |
| build_ways | task_brief、新手配置 | choice 断点 payload；决议轮写 build_way |
| guidance_trigger | build_way、新手配置 | guidance_mode（纯配置映射） |
| 8 配置条件边 | build_way × guidance_mode | 无——Actor 工厂参数每轮派生，不持久化 |
| 三方案并行 | 主线 grilling 历史 | proposal_set、choice 断点；选定轮写 selected_proposal |
| planner | task_brief、build_way/selected_proposal、交付物集定义 | todos（全 pending）、主环计数清零 |
| context_assembler | current_scope、rules 文件、todos 板、NOTES 切片（按 notes_version）、技能头、权限矩阵 | assembled_context、current_scope 落定；压缩检查（80% 阈值）可能产【R#-compact】 |
| actor | assembled_context（中间件送达）、私有历史、todos | 私有历史追加、todos 勾选、交付物落盘（带【R#】）、notes_version++、round_summary（后置工序）、turn_end_reason、current_scope 声明 |
| verifier | 磁盘交付物、todos | task_complete、is_docs_finished（LLM 判内容） |
| demo_actor | demo_messages（含融合的报错回传）、demo 文件 | demo_messages、demo 文件修复、demo 环计数 |
| finalizer | 全部交付物、会话产出 | final_report → Store |
| check_proper_output | 工作区全部文档 | output_clean、双份交付落盘；不过回 planner（终检环计数++） |

**入口路由真值表**（相位重建，纯代码——表驱动测试的直接素材）：

| 仪表盘现状 | 本轮入口 |
|---|---|
| task_brief 未设 | ask_tasks |
| build_way 未设 | build_ways 决议 |
| way4 且 selected_proposal 未设 | 方案选定 |
| todos 为空 | planner |
| is_docs_finished=false 且 todos 未清 | context_assembler（主环） |
| todos 清且 task_complete=false | planner（重新规划，主环计数++） |
| is_docs_finished=true 且 demo_phase=undecided | demo 决议 |
| 任一环计数=5 | loop_exhausted 断点 |
| task_complete=true | finalizer → check_proper_output |

**断点协议**（turn_end_reason × payload × 融合目标——主接缝测试的断言对象）：

| turn_end_reason | 触发 | payload | 下条输入融合到 |
|---|---|---|---|
| round | actor 轮终（默认） | 轮产出 + todo 板 | actor_messages |
| question | AskUserQuestion / grilling 提问 / ask 档指引询问 | 问题文本 + 选项 + 提问角色 | awaiting_input_from 指向的私有 key |
| choice:build_way | build_ways | 4 选项 + 推荐 + 一句话理由 | 决议节点写 build_way |
| choice:proposal | 三方案并行 | 3 方案摘要 | 决议节点写 selected_proposal |
| docs_done | is_docs_finished=true | 交付概览 + demo?/自定义 | 决议节点写 demo_phase |
| loop_exhausted | 任一环计数=5 | 现场与求助说明 | 自由融合（人工接管） |
| finished | check_proper_output 通过 | 双份交付路径 | 终态；旁路问答通道仍可用 |

**统一输入协议**：所有断点输入都是自由文本。选择类断点同样吃自由文本（含序号），由对应决议节点解释——不存在结构化 resume 值，与 Q46 一致。由此 **AskUserQuestion 实现为提问断点**（选项只作渲染辅助），不走工具内 interrupt——图内零 interrupt 的唯一例外维持为 shell 审批的 REPL 同步回调（不落 turn_end_reason、不进图）。此为 ADR-0001 对台账早期"HITL-in-tool"条目的覆盖裁决。代价：产生提问断点的节点必须可重入（提前返回后下轮重进不重复副作用）——与既有"节点写入幂等"要求同源。

### 上下文工程层

- **Assembler 两段式**：节点写 state（base prompt+作用域规则+todo 板+notepad 切片+工具子集声明）→ actor 中间件送达（@dynamic_prompt 组 system / wrap_model_call override tools / before_agent 版本号检查）。理由：create_agent 构造期固定后唯一官方每轮变化通道
- **摘要提炼（Q53=b）**：actor 节点内置后置工序——节点函数末尾、写 gate 前显式调用提炼函数，产出 round_summary + notes_version 自增。纯函数可单测
- **压缩（Q54）**：模型调用前统一检查——流程内所有 LLM 调用点（assembler/actor before_model/verifier/planner）挂同一压缩检查；80% 阈值触发，压最老 5 轮/包（便宜模型，Q7 子档）为【R#-compact】摘要；压后目标 ≤60%，不足再压一包（同轮最多两包）；最近 3 轮原文永不压缩；错误猜想写 Notepad；手动 /compact 兜底
- **注入位置（Q56）**：头部单包——全部压缩摘要合并为消息历史头部一个记忆区，每包首行标注覆盖轮次
- **作用域**：规则文件（rules/src.md、rules/docs.md…）+ current_scope state 字段；工具子集 = 规则声明集 ∩ 静态矩阵；Todo 自动勾选沿用电三态
- **技能懒加载**：上下文只注名字+一句话描述；SKILL.md 触发时才全文读入；推荐理由 ≤20 字代码硬约束
- **final_report**：finalizer 产出 → Store 跨线程长期记忆 → 新会话 ask_tasks 时可检索注入

### 工具权限

- **矩阵（代码层强制，构造期预注册）**：Builder/DemoAgent/way1 Actor = 全工具；AskAgent = 只读（FileRead/Glob/Grep/ReadProjectDocs/NotepadRead）+ 联网（WebSearch/WebFetch）+ 提问（AskUserQuestion）+ SkillRecommend + NotepadAdd；交付物 TODO.md 写权 Builder 独占
- **shell 权限**：静态正则检查器（8 类形态学：灾难删除/下载即执行/提权/凭证面/git 不可逆/网络出口/重定向/命令替换——独立于白名单、deny 全档生效、allow 命中也拦）+ 两旋钮（boundary: readonly/project-write/full 仅flag × interrupt: AI审核/全权人工/yolo 仅flag；决策模式 = interrupt 初值）+ 复合命令拆段 + wrapper 剥离 + 解析失败=ask（fail-closed）。Windows：rm 与 Remove-Item 别名都拦
- **DemoAgent 不运行 demo（ADR-0003）**：工具面 = 全工具（2026-10-24 修订，原"只读+脚手架"案作废），shell 仍过静态正则+两旋钮；唯运行类命令（执行 demo 本身）在权限层拒绝，运行权在用户；报错回传融合进 demo_messages，↺环受 demo 环计数约束
- **排除工具**：AgentTool/SkillTool/Plan Mode 两件/Task* 六件/SendMessage/NotebookEdit/MCP/LSP（v2+）

### 路由

- **REPL 混合路由三层**：斜杠命令（前缀匹配，零 LLM）→ 报错特征规则预筛（Traceback/Error: 等 + demo 阶段活跃）→ LLM 窄分类兜底（只判"报错回传 vs 普通输入"）
- **首启两层**：应用级（模型/API）与项目级（模式/指引/决策模式/技能包，首次进工作流时问）

### 模型与版本

- 主角色/子角色各自可配模型+key（可同 key）；压缩/摘要/窄分类走子档便宜模型
- 版本钉：langgraph>=1.2 且 langchain>=1.3.x（middleware/1.x API 代际）；Python
- 防雷：modify_state_before_agent 不存在（社区讹传）；middleware 细节 API 演进快，锁定小版本验证签名

### 可观测

- 本地 token 账单：usage_metadata 按 thread/角色聚合（输入/输出/总数）；shell 审计日志（规则 id+命令段+原因码）；不引入 LangSmith

## Testing Decisions

**测试哲学**：只测外部行为——"输入文本 → 可观察的轮终 state + 终端输出"，不测内部实现细节。接缝已与用户确认（1 主 + 3 支）：

- **主接缝 = REPL↔主图协议**：`invoke(user_prompt) → 轮终 state`。v1.1 起该协议有具体契约：**断点协议表 + 仪表盘字段表就是测试的断言对象**——回放脚本逐轮断言 turn_end_reason / turn_end_payload / 融合后目标 key 的变化；入口路由真值表逐行展开为表驱动相位重建测试。用可编程假模型 + 临时工作区回放完整会话脚本（ask_tasks 到 FINISH，含断点续跑/报错回传/压缩触发）。checkpointer 天然支持会话回放式测试
- **LLM 边界**：假模型按脚本出牌（"这轮假装推荐技能""这轮假装置 gate=true"），验证路由逻辑零真模型
- **工具边界**：假 shell（记录调用+预置输出），验证权限矩阵/静态正则拦截/两旋钮
- **磁盘边界**：tmp 工作区测【R#】写入剥离/Notepad 版本号/终检 diff

**测试代码与主项目物理分隔**（v1.1 钉板）：

- **目录树分离**：主项目采用 src 布局（单一主包）；测试树为独立顶层目录，两者互不嵌套
- **依赖分离**：运行依赖与测试依赖分组——测试依赖走独立可选依赖组（extras），安装主包不带测试件，跑测试才装
- **零反向依赖**：主包不 import 测试树任何内容；依赖方向严格单向（测试 → 主包）
- **测试替身不随主包分发**：可编程假模型、假 shell、会话回放脚本全部住在测试树，与生产代码无共享路径
- **配置分离**：测试运行配置（含异步配置、标记）独立于应用运行时配置

**重点测什么**（对应架构红线）：断点续跑的 state 融合正确性（按断点协议表逐行）；隔离红线（角色 A 的历史绝不出现于角色 B 的输入，指引通道同样受测）；gate AND todos 判定矩阵与入口路由真值表（多分支表驱动）；压缩边界（80% 触发/3 轮保护/水位 60%/两包上限）；静态正则的 8 类拦截；终检管线的"零残留+零误伤"；版本号排序的 stale-read 杜绝。绿地无先例测试可循。

## Out of Scope

- OS 级沙箱（容器/landlock）——v2+，v1 逻辑隔离已覆盖
- Web UI / Studio / 前端——已砍（v1 全 CLI）
- demo 自动运行/冒烟/自愈循环——ADR-0003 明确运行权在用户
- LangSmith / 云端观测——已钉不引入
- 余弦相似度/语义检索——v1 关键词+【R#】前缀够用，接口留 query 参数不堵路
- MCP/LSP/NotebookEdit/Task 系后台工具——v2+ 扩展点
- 新手模式强引导机制的进一步细化（用户自留）
- CLI 视觉美化方案（rich/textual 选型 = Q15 后置）
- 报错回传的启发式检测（第三层 LLM 兜底已覆盖）
- yolo/boundary=full 档的实际使用（仅保留 flag 定义）

## Further Notes

- 决策全量台账：.scratch/project-agent/decisions.md（47+ 决策含演化痕迹）
- 三份研究笔记：docs/research/langgraph-verification-2026.md（LangGraph 1.x 事实核查）、docs/research/shell-permission-survey.md（8 产品权限调研，10.2 节白名单 JSON 草案可直接改用）、middleware 核查结论（台账内嵌）
- 版本敏感警告集中在台账"middleware 事实核查"节——实现前先在锁定版本上验证 request.override/dynamic_prompt 签名；另需实测"END 后同 thread 再 invoke 从 START 重跑且 state 恢复"这一轮协议的底层行为
- v1.1 增补的推导性决策（待用户复核）：task_brief/turn_end_payload/awaiting_input_from 三个新仪表盘字段、环计数器分字段、demo_phase、图内指引无历史累积、AskUserQuestion=提问断点（覆盖台账旧"HITL-in-tool"条目）、节点可重入要求
- 里程碑顺序建议：REPL 壳+图骨架（断点跑通）→ 工具层+矩阵 → 上下文工程层 → 终检管线 → 账单。此顺序让隔离红线和断点这两个最难对的东西最早被验证；状态契约节是"REPL↔图协议"票与测试契约的直接依据
