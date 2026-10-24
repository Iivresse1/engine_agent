# 项目构建 Agent — 设计决策台账

Status: spec-v1.1（设计定稿，spec 已发布 ready-for-agent）
更新: 2026-10-24

## 已钉下的决策

| # | 决策点 | 结论 |
|---|---|---|
| Q1 | 产品形态 | v1 全 CLI（美观终端界面，具体 UI 细节后定）；Studio 体验 demo 作废 |
| Q2 | 交付物 | 增量构建的文档包（docs、目录树、配置、README、TODO），主 agent 在需求澄清过程中逐步成型；全部文档完成后可指令触发"基础可运行 demo" |
| Q3 | 目标用户 | 双用户路由：有编程基础（方案流，简洁高效）/ 无基础（强引导 + 子 agent 每轮输出构建理由与推荐下一步） |
| Q4 | 共享边界 | 只共享项目状态文档；对话历史完全隔离；子 agent 靠读共享文档作答，不读主 agent 历史 |
| Q5 | 消息路由 | 默认输入 → 主 agent；`/ask-for-help` → 子 agent（独立 thread_id，问答历史自累积） |
| Q6 | 构建档位路由 | 三档：简单脚本（IDEA.md 一页纸 + 短 grilling → 直连 DemoAgent）/ 个人作品（简化集：README+TODO+目录树）/ 复杂工程（完整集 + 3 套并行方案，interrupt 选定）。档位问题位于 onboarding 子图之后、builder 构建之前，然后接 route 用户输入环 |
| Q7 | 模型配置 | 双角色各自可配模型 + key；同一 key 时隔离靠代码（独立调用链 + 独立 thread）完全可行；服务商侧账单/限额共享，按 agent 记账需应用内聚合 |
| Q8 | 框架 | LangChain + LangGraph 硬约束；Python；钉 `langgraph>=1.2`（1.x API 代际） |
| Q9 | skills 包格式 | 复用 SKILL.md 文件夹格式；启动时选择加载哪些包；选择器中每条 skill 附原 SKILL.md 的注释/描述 |
| Q10 | 内置技能 | 完整内置 Matt Pocock 技能包；主 agent 按项目阶段推荐具体某一条；上下文只注入"名字+一句话描述"，全文懒加载 |
| Q11 | 技能推荐形态 | 推荐 = skill 指令 + interrupt 暂停 + 推荐理由（≤20 字，代码硬约束）；呈现分级由 Q19 决策模式参数化 |
| Q12 | demo 深度 | 工作区内生成 demo + 运行指南；用户自行运行；不做自动验证/自修复（v2+） |
| Q13 | 用户模式入口 | 启动时二选一："有一定编程基础 / 我不了解编程" |
| Q14 | 新手指引 | 新手模式再选一层：自动每轮给指引 / 每轮结束询问；指引 = 为什么这么做 + 涉及技术栈的文档链接；隔离 = 共享文档区（主 agent 写轮次摘要，子 agent 读文档区作答） |
| Q15 | CLI 框架 | ⏸ 后置 |
| Q16 | 后端形态 | ⏸ 后置 |
| Q17 | 共享介质 | 磁盘项目文档即共享事实来源；每轮生成物加【轮次】前缀标注（子 agent 按轮次读短切片，降低负担）；全部文档构建完成后删除轮次标记（finalize 步骤，幂等 + 零残留校验） |
| Q18 | 启动配置 | 首次启动问卷写入配置文件；之后零选择直达会话；斜杠命令随时改 |
| Q19 | 决策模式 | 启动选择：1. AI 自动审核（普通推荐=末尾附注不暂停，高风险命令人工决定）2. 全权人工（大部分决策 interrupt 暂停）。shell 确认策略已并入：模式 1=白名单自动+白名单外/高风险打断，模式 2=逐条人工确认 |
| Q33 | 路由门 | REPL 默认 = 通用 agent 架构执行用户 prompt（GeneralAgent，独立 thread）；输入 `/project-engineering` 才进入项目构建工作流（onboarding → 档位 → builder 环）；`/ask-for-help` 归属见 Q35 |
| Q34 | GeneralAgent 工具面 | 全工具形态：所有工具可调（含 DocScaffold/SkillRecommend/私有 TodoWrite），shell 走同一白名单+静态正则 |
| Q35 | /ask-for-help 归属 | 仅项目工作流内可用；工作流外问答直接给 GeneralAgent |
| Q36 | onboarding 拆分 | 应用级首启只问模型/API（各 agent 都要用）；项目级首启 = 首次 `/project-engineering` 时问模式/新手指引/决策模式/选包，之后直达 |
| Q37 | Max_loop | 固定 5（管 Finalizer 修复环、demo 报错回传环、grilling 防跑飞；耗尽 interrupt 交人工） |
| Q38 | 报错回传 | 直接粘贴报错、无显式命令（学正常 agent harness 的自由度），REPL 层意图判断路由；混合路由三层：显式斜杠命令优先（零 LLM）→ 规则预筛（Traceback/Error 特征直接判报错）→ LLM 兜底窄分类（只区分"报错回传 vs 普通输入"），普通输入默认去活跃 agent/Builder |
| Q23 | shell 权限系统 | **静态正则检查器**（灾难删除/下载管道/凭证路径/git 不可逆等 8 类形态学，独立于白名单、deny 全档生效含 yolo、allow 命中也照拦）+ **Codex 两旋钮**：boundary（readonly/project-write/full 仅flag）× interrupt（scaffold=模式1 / ask-all=模式2 / yolo 仅flag）；Q19 决策模式 = interrupt 旋钮初值；解析失败=ask（fail-closed）。v1 默认 boundary=project-write。Windows：rm 是 Remove-Item 别名，两者都拦 |
| Q23b | DemoAgent shell 边界 | ~~白名单只含只读探查+脚手架两类~~（**已被 2026-10-24 v2 修订覆盖**：DemoAgent = 全工具，唯运行类命令权限层拒绝，见矩阵表与 v2 节）；**不跑 demo**（Q12 维持 a 档）；**报错回传环**：用户自己跑 demo → 报错贴回 REPL → 路由进 DemoAgent 调试修改 → 用户再跑，循环受 Max_loop 约束 |
| Q28 | 档位提问位置 | onboarding 子图之后、builder 构建方案之前，接 route 用户输入环；形态默认"推荐档位+一句话理由+确认" |
| Q29 | 各档文档集 | tier1 = IDEA.md 一页纸（想法/目标/约定，grilling 完落盘，保住 ask 通道与 demo 上下文）；tier2 = README+TODO+目录树（跳过 spec/ADR/glossary）；tier3 = DocScaffold 完整框架（含技能包格式文件扩展） |
| Q30 | 多方案生成 | 仅复杂工程档：grilling 到位后并行 3 套方案（技术栈 × 复杂度取舍维度），interrupt 选定后深化；其余档单方案 |
| Q31 | TodoWrite 归属 | 工具收归 Builder 独占（交付物 TODO.md 单写者+【R#】）；各 agent 内部计划 todo = 私有 state 字段（不落盘不共享不经工具） |
| Q32 | 内部 todo schema | 三态：`list[{content, status: pending\|in_progress\|completed}]`，agent 私有 state key；in_progress 支撑进度渲染与中断恢复 |
| Q20 | 宿主形态 | CLI REPL 主循环当总机：解析斜杠、分发到独立编译的子图（builder/ask/demo/finalize 各自 thread_id），并维护"当前活跃 agent"（AskUserQuestion 全员开放的答案回路由） |
| Q21 | 新手覆盖层挂载点 | builder 图内条件后置节点：每轮主内容完成后，图内判 novice → auto 档直接进 guidance 节点；ask 档先 interrupt 问"本轮要不要指引"，要才进。指引完回 REPL |
| Q22 | Finalizer 设计 | 剥标记管线（并入 REPL 宿主）：LLM 检测标记（含畸形变体）→ 快照备份 → 正则移除 → 确定性 diff 校验（变更行只含标记）→ LLM 语义校验（删除前后内容一致）→ 备份版+干净版两份都交用户。缺文档/不一致 → 回 builder 开**新完整 Loop**（非单轮补丁），受 Max_loop 限制；耗尽 → interrupt 交人工 |

## 首启流程（Q36 拆分为两层）

**应用级首启**（首次启动 REPL）：
1. 模型 + API 配置（主/子 agent 各自，可同 key；GeneralAgent 用哪档也在此配）
→ 写入配置文件，直接进通用会话；非首启零问题直达

**项目级首启**（首次输入 `/project-engineering`）：
1. 用户模式：有一定编程基础 / 我不了解编程
2. （仅新手）构建指引：自动每轮 / 每轮询问
3. 决策模式（=shell interrupt 旋钮初值）：AI 自动审核 / 全权人工
4. skills 包选择（附描述）
→ 存入项目配置；之后进工作流直达

## 阶段闸口（interrupt 必停）

- 方案选定确认（tier3 三选一）
- 文档全部完成 → `/build-demo` 入口
- finalize（清除全部轮次标记，产出备份版+干净版两份）
- 决策模式 2 下：每条 skill 推荐；模式 1 下另加高风险命令（静态正则 deny 类 + 白名单外 ask 类）
- Max_loop=5 耗尽时（Finalizer 修复环 / demo 报错回传环 / grilling 防跑飞）

## 工具权限矩阵（钉板 2026-10-23 全量）

参考：Claude Code 默认工具集（xuanyuancode.com 源码学习专题，25 工具）。

| 工具 | Builder | AskAgent | DemoAgent | GuidanceAgent | GeneralAgent |
|---|---|---|---|---|---|
| FileRead / Glob / Grep | ✅ | ✅ | ✅ | ✅ | ✅ |
| ReadProjectDocs（只读+【R#】切片） | ✅ | ✅ | ✅ | ✅ | ✅ |
| FileWrite / FileEdit | ✅ | ❌ | ✅（覆写） | ❌ | ✅ |
| TodoWrite（私有计划，三态） | ✅ | ❌ | ❌ | ❌ | ✅ |
| WebSearch / WebFetch | ✅ | ✅ | ✅ | ✅ | ✅ |
| Shell | ✅（静态正则+两旋钮） | ❌ | ✅（**全工具**，2026-10-24 修订；不跑 demo 维持，报错回传环兜底；shell 仍过静态正则+两旋钮） | ❌ | ✅（静态正则+两旋钮） |
| AskUserQuestion | ✅ | ✅ | ✅ | ✅ | ✅ |
| DocScaffold（文档框架生成） | ✅ | ❌ | ❌ | ❌ | ✅ |
| SkillRecommend | ✅ | ✅ | ❌ | ✅ | ✅ |
| 交付物 TODO.md 写权 | ✅（Builder 独占，【R#】） | ❌ | ❌ | ❌ | ❌ |

明确排除（钉板）：AgentTool（子 agent 路由归代码，隔离红线）、SkillTool（skill 执行权=用户斜杠触发，Q11）、Plan Mode 两工具（档位路由+方案阶段即对应物）、Task* 后台六件、SendMessage（agent 间只走共享文档区）、NotebookEdit、MCP/LSP（v2 扩展点）。

原则：
- 权限白名单在代码层强制（`create_agent(tools=[...])`），LLM 不可越权。
- AskUserQuestion 全员开放 ⇒ REPL 必须跟踪"当前活跃 agent/thread"（子 agent 提的问题，答案要路由回该子 agent 的 thread，不能默认落 Builder）——Q20 的 REPL 设计需覆盖。
- 术语澄清：TodoWrite 工具 = agent 私有计划面板（三态，Q32，不落盘不共享）；交付物 TODO.md = Builder 独占写权（Q31，带【R#】）。两者是不同对象。
- GeneralAgent 的 DocScaffold/SkillRecommend 在通用会话语境中语义为"帮用户搭文档框架/推荐技能"，不触发项目工作流状态。

## 图结构重设计 v2（2026-10-24 定稿中，用户主导）

**应用架构（Q40 修订）**：大图 = 核心工作流引擎（非整个应用）；REPL 宿主保留（I/O 壳 + 斜杠 + 活跃 agent 跟踪 + 混合路由）；way1 吸收 GeneralAgent（门外不再有独立通用 agent）；AskAgent 保留为 REPL 旁路 + 图内 guidance 触发（Q41）。

**主图**（顺序按用户澄清：planner 在 actor 前，actor 组件内含 loop）：
```
start → ask_tasks → build_ways(4选1) → guidance_trigger(3态)
  → conditional_edge(4×2=8 配置 → actor 工厂参数化)
  → planner(todo清单) → actor(内含loop; way1=ReAct / way2-4=grilling)
  → verifier(LLM判断→置位gate变量组) 
  → conditional_edge(读gate变量: 回planner↺Max_loop=5 / interrupt人工 / 放行)
  → [way3/4: is_docs_finished=true → interrupt"demo?/自定义"]
       demo → demo_actor(报错回传环↺) → check_proper_output
  → finalizer(收尾整理) → check_proper_output(=Q22质检管线) → FINISH
```

**v2 新钉决策（Q40–Q45 + 2026-10-24 下午修订）**：
- Q40：大图非整个应用；REPL 保留；GeneralAgent 并入 way1
- Q41：AskAgent 保留（REPL 旁路拉式 + 图内推式 guidance），**吸收 GuidanceAgent 全部职能**（guidance_trigger = 是否开启 AskAgent 新手指引）
- Q42：三态 = 自动每轮 / 每轮询问 / 关
- Q43（修订）：检查闸门 = gate 变量组（task_complete / is_docs_finished / output_clean / loop_count）**AND todos_all_completed（与关系）**；todos_all_completed 为纯代码判定（三态清单全 completed）。planner 产出的 todo 清单 = 全局 state（工作流产物）；actor 自身草稿仍私有
- Q44（修订）：verifier 置位 is_docs_finished；后续以**断点**承接（见 Q46）
- Q45：planner 对应所有方式
- Q46（新，2026-10-24）：**断点机制全面取代 interrupt**——图内零 interrupt() 调用。断点 = 轮终交还控制权：节点把"等待用户"作为本轮终态（state 暴露 turn_end_reason），checkpointer 存状态，REPL 收自由 prompt → 下次 invoke(同 thread) 经 reducer 融合进消息历史 → 图从当前位置继续。用户输入是自由 prompt（开放续写），不是结构化 resume 值。原 7 处 interrupt 全部改断点；唯一例外 = shell 审批走 REPL 宿主层同步审批回调（harness 职责，非图机制）
- DemoAgent 权限（修订，2026-10-24）：**全工具**（原"只读+脚手架"案作废；用户例：中间件实验报告=way1 任务仍需调 DemoAgent 读写文件）。shell 仍过 Q23 静态正则+两旋钮（工具层，与角色权限正交）

**草稿图里缺失、需挂回的已钉决策**（思辨提醒，2026-10-24）：
- Q30 三方案并行（way4 专属：grilling 到位 → 3 套并行 → interrupt 选定 → 才进 planner）
- Q36 两层首启（应用级=REPL 启动时模型/API；项目级并入 ask_tasks/build_ways 流程）
- Q17【R#】轮次标记 + 共享文档区；Q10 技能懒加载；Q11 SkillRecommend ≤20字
- Q23 shell 权限（静态正则+两旋钮）挂工具层；Q38 报错回传环接 demo_actor
- Q22 完整质检管线 = check_proper_output（LLM检测→快照→正则→diff→LLM校验→双份交付）
- Q39 token 记账（仍未定）；AskUserQuestion 工具内 interrupt（HITL-in-tool，LangGraph 原生）
- interrupt 恢复语义：verifier 节点含 interrupt 时恢复会重跑整节点 → 置位/写盘须幂等

**待办（用户路线图）**：完成图 → 探讨 context engineering 如何加入 → harness engineer 实现（用户将提供图示，本轮附件未能接收，待文字描述）

## 上下文工程层 v3（2026-10-24 下午，用户提供：7 模块 + harness 4 需求 + NotepadRead/NotepadAdd）

**钉板（Q39/Q48–Q52，2026-10-24 17:00）**：
- Q39 Observe/token 记账 = **本地账单**（usage_metadata 按 thread 聚合），LangSmith 不引入（用户：会干扰主线设计）
- Q48 Assembler = **图内显式节点** context_assembler，位于 loop 头部每轮跑
- Q49 Notepad = 项目工作区 NOTES.md，条目带【R#】；NotepadAdd/NotepadRead 全 agent 可用；**排序约束：AskAgent 永远在主 agent 写完 NOTE+摘要之后才可调用**——state 版本号机制（notes_version / guidance_read_version）+ hook 形态待定（用户已确认 Q49 整体方案 ✅ 2026-10-24）
- Q50 压缩 = 自动阈值 **80%** → 便宜模型压最老 n 轮（**n=5/包**）入 state 摘要【R#-compact】→ 原文 delete；水位目标压后 ≤60%（不足再压一包，同轮最多两包）；最近 3 轮原文永不压缩（工作记忆）；错误猜想写 Notepad；手动 /compact 兜底（**用户已确认 n=5 设计 ✅ 2026-10-24**）
- Q51 作用域 = 规则文件（rules/src.md、rules/docs.md…），current_scope 为 state 字段，Assembler 换规则+裁工具子集（规则声明集 ∩ 静态矩阵）
- Q52 final_report = 最终会话输出为 final_report 变量 → 长期记忆库（LangGraph Store，跨线程）→ 供下一个新会话检索注入

**余弦相似度裁定（2026-10-24）**：v1 不引入。单项目 Notepad 条目量小（几十条），关键词/【R#】前缀检索够用；final_report 跨项目语义检索是 v1.5 价值区（Store 加 embedding index 不改 API，接口留 query 参数即可）。

**Q49 排序机制（预设计，hook 形态待核查）**：state 加 notes_version（NotepadAdd 后自增）与 guidance_read_version（AskAgent 读后对齐）；guidance 节点入口检查 version 差 → 有新 NOTE 才注入最新摘要 → 读毕对齐。stale-read 被结构性杜绝。

**Middleware 事实核查（2026-10-24，docs.langchain.com 官方，子代理 09ce722a）**：
- `AgentMiddleware`（langchain.agents.middleware）为 v1 定义性特性。hook 全集：node 式 4 个（before_agent/before_model/after_model/after_agent，签名 `(state, runtime) -> dict|None`，返回 dict 经 reducer 写 state）+ wrap 式 2 个（wrap_model_call/wrap_tool_call，`request.override(tools=...)`、`Command(update=...)`）+ `@dynamic_prompt` 装饰器
- **动态工具选择官方路径** = wrap_model_call 里 `request.override(tools=子集)`；工具必须 upfront 预注册 → **静态权限矩阵=预注册全集，作用域=每调用过滤**——Enforce 与动态选择在官方机制上闭合
- 官方分工（原文意译）：拓扑级（agent 间路由/并行/确定性缝合）→ StateGraph 节点+条件边；agent 循环内横切（注入/裁剪/摘要/守卫）→ middleware；`jump_to` 只能 end/tools/model（做不了 agent 间路由→路由留在图上，与 Q20/Q46 一致）
- 内置 `SummarizationMiddleware(model, trigger=("tokens",N), keep=("messages",M))` = Q50 压缩的官方同型（hook 内跑 LLM 官方支持）；我们自写定制以支持【R#-compact】/n=5 包/notepad 错误猜想
- hooks 运行在 create_agent 编译出的图**内部**，agent+middleware 可作为 StateGraph 节点嵌入 → **v2 单图 + middleware 增强 actor 的整体架构获官方背书**
- callbacks = 只读观测（定位收窄）；StreamTransformer = 观测层不可写 state（token 记账仍走 usage_metadata 聚合，Q39 不变）
- ⚠️ `modify_state_before_agent` 不存在（社区讹传，勿写码）；版本钉升级为 langgraph>=1.2 **且 langchain>=1.3.x**
- AskAgent 双通道落点：图内 guidance 路径 = before_agent 版本号检查 + @dynamic_prompt 注入最新 NOTE+摘要；REPL 旁路 = 每次调用直读磁盘 NOTES.md（天然最新，无 staleness 问题）

**Q53（终裁 2026-10-24）**：摘要提炼挂载 = **(b) actor 节点内置后置工序**——用户终裁选显式节点路径，推翻中间件推荐。提炼函数在 actor 节点函数末尾、写 gate 变量之前显式调用（可断点、可单测、与 Q48 Assembler 前置节点对称）。middleware 仍用于其余横切（工具 override/dynamic_prompt 注入）。

**Q54（终裁 2026-10-24）**：压缩触发点 = **模型调用前统一压缩**——流程内所有模型调用点（assembler 压缩检查、actor 的 before_model、verifier/planner 等任何跑 LLM 的节点）都挂同一压缩检查（80% 阈值水位检查 + Q50 算法）。实现为可复用函数/中间件，挂到每个 LLM 调用前置位。90% 应急阀不再需要（模型调用前统一检查已覆盖轮内增长）。

**Q56（终裁 2026-10-24）**：压缩包注入 = **头部单包**——所有【R#-compact】摘要合并为消息历史头部一个"历史记忆区"（带目录：每包首行标注覆盖轮次），reducer 默认行为直接支持，不需要自定义。

**Q55（原理已解释，待用户确认）**：Assembler 两段式——节点写 state（装什么）+ actor 中间件送达（送进去）。@dynamic_prompt / request.override(tools=) 是 create_agent 构造期固定后唯一的官方每轮变化路径。

**Q47（终裁 2026-10-24）**：不做 archify 渲染，终稿图以简图形式在会话中交付。

**Harness 四需求映射结论**：Gate=Q23 已建｜Enforce=矩阵代码强制已建｜Persist=checkpointer+断点(Q46)已建｜Isolate=独立thread+私有state已建(OS级沙箱 v2+)｜Observe=本地账单(Q39)已定


**Q57（spec v1.1 增补，2026-10-24）**：图状态契约钉板——
- 轮的机械化：一轮=一次完整图执行（START→END），断点=END+turn_end_reason 落盘；入口路由器（START 后纯代码条件边组）读仪表盘重建相位，无需 mid-graph 挂起
- 仪表盘新增字段（推导，待复核）：task_brief / turn_end_payload / awaiting_input_from / demo_phase；环计数器分三字段（主环/demo 环/终检环各 Max_loop=5，互不污染）
- AskUserQuestion=**提问断点**（选项仅渲染，答案自由文本融合）——ADR-0001 覆盖台账早期"HITL-in-tool"条目；代价=产生提问的节点须可重入（与既有幂等要求同源）
- 图内 AskAgent 指引调用无历史累积（当轮材料包单发，绝不写主线历史）
- 测试与主项目物理分隔：src 布局 + 独立测试树 + extras 依赖组 + 零反向 import + 测试替身不随主包分发
- spec.md 断点协议表/仪表盘字段表/入口路由真值表 = 主接缝测试的断言契约（表即契约）

**Q58（to-tickets 定稿，2026-10-24）**：spec v1.1 拆 12 张 tracer-bullet 票（用户批准），发布于 .scratch/project-agent/issues/01–12。关键裁定：06 上下文工程层拆两张（08 压缩 / 09 两段式+作用域+懒加载）；demo 票依赖压缩票（DemoAgent 轮也是 LLM 调用点）；token 账单独立小票（04）不并入 01（tracer bullet 纪律：第一颗子弹只打最难的靶=断点+路由）。过票中补上两个草案缺口：way2–4 构建形态独立成票（07）、AskAgent 双通道独立成票（10）。前沿演化：01 → {02,03,04} → 05 → 06 → {07,08,09} ∥ → {10,11} → 12。所有票 Status: ready-for-agent。

**Q59（01 票实现事实，2026-10-24 深夜）**：
- 环境复活：pwsh 5.1.26100 / Python 3.12.4 (venv) / git 2.56；早先 exit 3221225794 状态消失
- 实测钉版本：langgraph 1.2.17 / langchain 1.4.7 / langchain-core 1.7.0 / pytest 9.1.1（vs 台账钉的 langgraph>=1.2 且 langchain>=1.3.x ✓）
- **版本敏感行为实测通过**：END 后同 thread 再 invoke 从 START 重跑且 state 恢复 ✓（轮协议的底层前提成立）；START 出发 conditional_edges ✓；`langgraph.graph.message.add_messages` ✓
- 冒烟发现并钉板两条：①每条可达路径必须写新断点（build_ways 解释不了输入时写 fresh round_end，防 stale turn_end 重渲染）——补为协议级原则；②管道态 stdio 统一 UTF-8（Windows 管道默认 GBK，入口处 reconfigure）
- ModelClient 协议（role/thread_id 挂钩）先行落地供 04 票账单挂靠；测试 61 绿；提交 ea9b94c
- **code-review（两轴并行子代理）结论与修复（提交 090bf5c，测试 64 绿）**：
  - Spec 轴两真缺口已修：①断点持久化落盘——CLI 接 SqliteSaver（--state/--new-session，thread_id 会话文件持久化，跨进程重启续跑实测 ✓）；②round payload 补 todo_board 三态板、choice:build_way 拆 recommendation_reason
  - Standards 轴已修：GLOSSARY 术语（REPL 壳→REPL 宿主、轮终→断点）；repl 复用 MAINLINE_KEY；io 走 config.IO 协议；斜杠改前缀匹配
  - **02 票前置欠账（评审裁定记档）**：RESOLUTION 类融合降级为融主线（02 决议节点落位时升级）；FINISHED 终态后 01 骨架仍融合主线（终态旁路语义后续票）；角色键 actor/demo 与 way1-4 裸串待枚举化（Primitive Obsession，弱）；**02 票承诺**：build_ways"推荐+一句话理由"走 ModelClient——成为第一个假模型驱动的图节点测试（01 图内零 LLM 调用故替身无处驱动）
  - Spec 轴复审补充修复：loop_exhausted payload 补 scene 字段（spec L204"现场与求助说明"）
  - 空树 diff 技巧：`git hash-object -w -t tree <空文件>` 物化空树作单提交仓库的评审固定点

**Q60（implement-spec 流水线，2026-10-25 凌晨）**：01 骨架（4 提交）+ 04 账单（8 提交，合并 c56c57d，75 绿）落 integration/project-agent 分支。流程纪律钉板：①implementer 派工单必须自带完整预裁设计——02/03 首派皆因子代理自行推演耗尽上下文零提交，预裁重启后正常推进；本项目票粒度=整套状态机+协议交互，超出子代理读材料自推演的预算；②合并者对每票做三件事：票收口（Status done+勾选+Comments）/ 台账 Q 记录 / 集成分支全量测试验证；③04 遗留接线待办两条：MeteredModel 挂 cli 装配（02 合并时做，账单路径 --state 同目录）、AuditLog 接 03 权限 checker 事件（03 合并时做）。
- 03 票完成（implementer 子代理，合并 e59f1fe，219 绿）：tools 包七模块 + shell_policy.json（§10.2 草案改用：管道 deny 规则删/git clone 留 ask/allow 拆 read-write）；内联脚本删除扫描增强（bash -c 'rm -rf ~' 也命中类 1）；AST 测试钉死 ADR-0001 例外边界（审批模块零图层 import）。设计裁定回填：8 类全 DENY（deny 全档生效含 yolo）、AskAgent 含 NotepadRead 共 10 件（spec v1.1+Q49 覆盖票面"四件"缩写）。
- 02 票完成（implementer 子代理，合并 2b59e1b，330 绿）：01 三笔欠账全清（Role 枚举/resolution_inputs 通道/REPL FINISHED 终态）；问卷四问跨轮机制（task_brief 从首条人类消息写定）；choice:build_way 断点流（ModelClient 首个图内驱动）；guidance_trigger 纯映射落图。**spec 升 v1.2**（Lead 补录）：仪表盘 +user_mode/guidance_pref/decision_mode/skill_packs、私有 key 表 +resolution_inputs；Q4 选项文案为票内发明记档。审计接线已做（c74aa49：ShellTool 可选注入 AuditLog，deny/ask 判决时刻落账）；MeteredModel→cli 装配仍待（05 票 Actor 引入真 ModelClient 注入点时做）。

**Q61（05 票主环拓扑终裁，2026-10-25 凌晨）**：一轮=一次 invoke 必到 END；**主环跨 invoke 续跑（轮节律制）**——每工作轮 = context_assembler→actor→verifier→END（round 断点），用户下条输入融合进 actor_messages 驱动下一轮；清而未过轮 = verifier→PLANNER（同轮重新规划）→planner→END；计数=5 轮 = verifier→LOOP_EXHAUSTED→END。图内唯一回边 = verifier→planner。**裁定依据**：①"每轮 turn_end_reason/assembled_context 每轮覆写"只有跨 invoke 可断言；②用户故事 17（每轮交还控制权）+ way1"正常 agent 对话节律"同构；③CLI 无真模型时每轮必终止（图内无界 assembler↺ 环会挂死骨架 CLI）；④spec 入口路由真值表主环行全部变活代码（图内环方案下是死代码）。派工纪律第三次升级：**预裁必须零决策点**——02/03/05 首派各烧掉一整个子代理上下文（02 在问卷跨轮机制、03 在 8 类正则语义、05 在本拓扑歧义）；终裁版派工单把裁定连同图拓扑伪代码直灌，子代理纯执行。
- 05 票完成（合并 f689b88，421 绿，+91）：**耗尽态不对称设计钉板**——图内边 _after_verifier 计数最前（耗尽即时触发）；入口边 todos 先序（耗尽恢复输入 → planner 见 count>=5 清零开新循环）。Lead 曾拟"入口也计数先序"，分析后撤回：会卡死恢复路径（耗尽态=清+false+count5 永远再判 LOOP_EXHAUSTED），且 spec 真值表行序即 todos 先序——实现者的异议裁定正确。Role.+VERIFIER（ModelClient.role 受控词汇扩展，fusion 映射未动）；PLACEHOLDER 全删；model=None 时 actor→END 直连（骨架防挂死，真模型票闭合 verifier 环）。
- 06 票完成（合并 2620011，467 绿，+46）：shared_docs.py（SharedDocs+版本门纯函数）；actor 落盘扩展（round_count/【R#】/"记录："指令桥）；graph +workspace_root；spec 升 v1.3（+round_count）。**前沿解锁：07/08/09 三票并行**。边界钉定："记录："单层 split；read_round 同轮取首。
- 07 票完成（合并 31293df，564 绿，+97）：deliverables.py 定义表（12 票对账对象）；grilling 身体；"写入："行首解析+白名单落盘；way4 DocScaffold 框架先行；三方案并行节点（PROPOSALS 入口行插 todos 前）。
- 09 票完成（合并 7890bd1，594 绿，+29）：scopes/skills 新模块；assembler 工厂化五段 system+版本门；actor system 尾行工具清单送达。**关键终裁**：工具子集送达弃用 langchain middleware（版本敏感），走 assembler 装入+actor 尾行——语义等价零版本风险。与 07 的 nodes.py 三处冲突由 Lead 手工解（工厂骨架+脚手架织入/助手全留/尾部组合）。
- 08 票进行中（三路并行最后一票）。

## 挂起 / 待办

- Q39 token 按 agent 记账落地（= harness Observe 模块的具体化）
- Q48–Q52（上下文工程层边界问题，已摆）
- Q47 archify 渲染交互式架构图（待图定稿）
- Q15 CLI 框架 / Q16 后端形态 / CLI 界面细节（后置）

## 事实核查基准

见 `docs/research/langgraph-verification-2026.md`（LangGraph 1.x，2026-10）。
关键结论：Store 跨线程共享 ✅ / thread_id 隔离 ✅ / subagents-as-tools 思考隔离 ✅ / interrupt+Command(resume) 持久等待 ✅ / 按 agent token 记账需自建 ⚠️ / langgraph-supervisor 已停维护（自行组装路由）⚠️
