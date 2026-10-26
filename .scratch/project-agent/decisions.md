# 项目构建 Agent — 设计决策台账

Status: 12 票实现完成 + 终局评审收口 + /retro 环境改进落地 + 真模型接线落地 + 13/14 票（teach-me / UX-1 壳票）落地（**spec v2.0**）
更新: 2026-10-26

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
- 08 票完成（合并 57c8487，660 绿）：compression.py 四边界/头部单包/猜想提取；重排=add_messages 指令批（首条覆写+RemoveMessage——**消息历史收缩的 LangGraph 正确方式**，02 票 decisions 里"resolver 默认行为直接支持"的判断在删除场景被证伪，指令批才是收缩正道）；with_compression 三挂点；/compact 待并批（压缩批必须随下轮 invoke 进图否则 checkpointer 历史永不收缩）；spec 升 v1.4（+compacted_rounds）。**执行注记**：子代理死于切片 4/5 之交（第四次耗尽），Lead 接手收尾——教训：长票切片 4+ 是子代理上下文高危区，后续票派工切片数压到 ≤5 且最后一片只做合并。**07/08/09 三路并行全部收齐——前沿解锁：10/11 两票并行**。
- 10/11 首派三代理集体 failed（2026-10-25 08:00 前后，含 08 已死的旧代理迟到通知）——环境级中断，两 worktree 零残留零提交。12:10 重启（goal resume）：确认 worktree 干净/venv 重建，两票终裁版派工单原样重发。教训补充：批量并行代理对宿主稳定性敏感——中断后先查 worktree 残留再决定重派，避免重复劳动。
- 10/11 二派双双交付但均死于汇报前（10 票全 5 切片+合并完成仅未发汇报——Lead 查 worktree 发现 682 绿直接采用；11 票 4 切片完成死于切片 3 提交后——Lead 提交遗留测试+融合 10 的 /ask-for-help 与指引块入 11 分支）。合并 baa66ea（733 绿）。**10 票语义注记**：assembler（09）与指引（10）共用 guidance_read_version 门——assembler 先消费，图级指引只在 actor 同轮自增 NOTE 时触发；未裁定门归属前按字面实现。**11 票接口扩展**：with_compression +messages_key（demo 挂点 demo_messages）；Role.+DEMO_AGENT；SharedDocs.+write_any；routing 行 7→DOCS_DONE（12 票接管终态）。**前沿解锁：12 终检管线（最后一张实现票）**。
- 12 票完成（合并 08bc4b7，791 绿，+58）：final_check 终检管线/memory_store/finalizer+check 节点/终检环。**拓扑终局**：DEMO_AGENT→FINALIZER（demo 后同轮进终检）；入口行 8=skipped 直通终检。**全部 12 张实现票完成（02–12，01 为先行骨架）——进入终局 code-review 收口**。剩余异议：终检新环 planner 模板板覆盖修复 todo（修复项持续性）；guidance_read_version 门归属（assembler vs 指引通道）——两项留 v1.5 裁定。

**Q62（终局 code-review 两轴，2026-10-25）**：架构四红线全守住（零 interrupt/磁盘共享/demo 不运行/私有 key 隔离）+ 三张契约表全符（7 reason payload/融合目标、仪表盘 26 字段、真值表行序——两处字面不符属 11/12 有据改道）。**已修**：①术语（修复回合→循环）；②三处 payload 复用统一 _reuse_payload(state, reason)；③**/mode、/skills 运行时命令补齐**（用户故事 3 票拆分漏项——/mode 查改决策模式含中文别名，/skills add/remove 查改技能包，+11 测试，802 绿）；④spec v1.5 回填（入口路由真值表随 11/12 改道更新——"表即契约失守"批评成立；BUILD_LOG.md 载体记档）。**v1.5 背欠清单（接线票，非实现缺陷）**：工具执行回路（actor 无工具调用环，全靠文本指令桥）/decision_mode·skill_packs 图内零消费者/AskUserQuestion 工具本体/TodoWrite 私有面板 key/旁路 checkpointer 持久化/current_scope actor 写者/verify_link 接入指引/final_report 检索注入 ask_tasks/ask 档 question 断点循环/压缩挂点 finalizer+旁路+指引/finalizer 后 LangSmith 正式 Store。**Standards 轴 turn 命名族裁定**：字段名 spec 钉定不改；TurnEndReason 枚举名/_run_turn 方法名可改但涉及 12 票测试面，收益/成本比低——记档不修。

**Q63（/retro 环境改进六候选落实，2026-10-25）**：按严重度 1→3→4→2→5→6 全部落地，803 绿零警告。
- **护栏（1，提交 e6257da）**：pytest `filterwarnings=["error"]`——602 警告**治本归零零 ignore**：节点 config 注解 `Optional[Mapping]`/`Any`→`Optional[RunnableConfig]`（**langgraph 1.2.17 签名白名单只认 typing.Optional 形式，PEP 604 `| None` 反触发警告且 config 不再注入**——nodes.py 源码级注释钉死防倒退）；onboarding docstring r-string 修 `\W` SyntaxWarning。ruff 窄规则集 E4/E7/E9/F/W/I（风格判断项 UP/SIM/BLE 不进检查）+ tests 放宽 F841；26 条自动修。`.githooks/pre-commit`（ruff+pytest 全量，钉 .venv）经 `core.hooksPath` 接线；**红绿双向实测**（负例 F401 拦下）。坑记档：仓库 .venv 是唯一可跑环境（全局 anaconda 缺 langgraph-checkpoint-sqlite）；pyproject +`pythonpath=["src"]` 修根目录裸 pytest。
- **playbook（3+6，提交 7afceda）**：`docs/agents/implement-spec-playbook.md`——零决策点派工单五要素（02/03/05/08 四死根因）/切片≤5 末片纯收口/残留优先死亡处置（10/11 票实测）/Windows patch BOM 坑一行；AGENTS.md 加派工指针（派工前/子代理死亡时两触发分支）。
- **契约对账（4，同 7afceda）**：issue-tracker.md 票收口规则——Dashboard 字段/路由真值表改动必须回填 spec+契约测试，表与代码不一致=票未收口。
- **术语哨兵（2，提交 3b75afa）**：`tests/test_glossary_sentinel.py`——AST 拆词（Camel+snake）对 GLOSSARY `_Avoid_` 单词子集机械强制；tools/ 路径豁免 interrupt/flag（Q23 裁定域术语）；turn_end_reason/payload 标识符豁免（spec 钉死键镜像）；agent/memory/多词避免词判例记哨兵 docstring 不机械禁。**Q62"记档不修"翻案**：TurnEndReason→RoundEndReason 实测仅 5 文件机械替换（12 票测试面成本当时高估），_run_turn/_invoke_turn→_run_round/_invoke_round 同批；字符串键 turn_end_reason/payload 维持 spec 钉定。红绿双向实测。
- **导航（5，提交 a95cfa7）**：nodes.py 模块 docstring 相位目录（入口/主环/demo/终检/压缩横切，函数名锚点非行号——行号会腐烂）；旧 docstring 停在骨架时代只述 4/14 节点家族。按相位拆四文件的替代方案留待裁（v1.5 接线背欠继续增长时再议，拆有合并成本）。

**Q64（真模型接线票，2026-10-25 傍晚，用户令"先把模型配置起来"）**：Q62 背欠清单首项落地，818 绿零警告，真 DeepSeek 端到端实测。用户明示两条安全要求：①密钥可从桌面 storage/apikey.txt 读取；②配置落 .env 或 yml + .gitignore 防推送泄露。
- **配置切 .env**（`~/.project-agent/config.env`，KEY=VALUE 平面）：yml 被否（PyYAML 进依赖树违背零冗余）；.env 是密钥文件惯例零新解析依赖。旧 config.json 首读自动迁移（读 json→写 .env→删 json 一次性）；**BOM 容错**（pwsh 管道伪影冒烟实测：parse_env 剥 \ufeff + 问卷输入行 lstrip）——Q63 遗留的加固候选顺手清掉。
- **OpenAICompatClient**（openai_client.py）：ChatOpenAI 打 OpenAI 兼容端点（DeepSeek/官方皆可）；`base_url` 缺 scheme 归一补 https://（用户手填 "api.deepseek.com" 不补则 openai SDK 报错）；langchain_openai **惰性导入**（模块导入零网络，测试注入 chat 桩即零依赖跑协议面）；usage 双路读取（usage_metadata 优先→response_metadata.token_usage 兜底）。
- **runtime.py 一站装配**：主/廉价客户端各包 MeteredModel 共享 TokenLedger（--state 同目录 ledger.json）；cheap=sub_model 缺省同主（同一实例省一次构造）；AskBypass 独立 thread（`{thread_id}-ask` 后缀，ADR-0002 物理隔离）；client_factory 注入缝=测试零网络全链路。
- **cli.py 接线**：build_graph(model=…, cheap_model=…, workspace_root=cwd) ——verifier 环闭合、压缩横切四挂点亮、/compact 与 /ask-for-help 可用；banner 去"01 骨架"字样。05 票 TODO 哨兵测试退役改钉真接线（"TODO not in src"反向断言）。
- **.gitignore 加固**：.env/.env.*/*.env/config.json/ledger.json/state.db/state.db.session.json/.project-agent/——密钥与本地状态全类目防推送。
- **端到端实测**（真 DeepSeek key）：问卷四问→重启续跑→build_ways 真模型调用（recommendation "轻 grill"+个性化理由，非静态兜底"完整文档"）→ledger.json 落账 actor 1 调用 59入/16出。**主环正式活**——`再聊聊`类自由输入即走 assembler→actor→verifier 全环；actor 实测自发调技能（grilling/to-spec/tdd 头注入生效），way1 决议+规划轮+对话轮三连冒烟全过。
- **续跑断点回灌 bug（冒烟发现即修，+3 测试 821 绿）**：跨进程重启在 RESOLUTION 类断点（choice:build_way）上丢首答——ReplHost 启动时 _last_state 空，fusion 把答案当 reason=None 融主线而非决议通道，choice 原样重发。修复 = run() 起手 `_seed_state_from_checkpoint()`（app.get_state 回灌末态；桩 app 无 get_state 跳过）。红绿双向验证（禁用回灌→红）。**根因属 01 票"断点持久化"欠账的盲区**：当时只验证了 question 类断点续跑（fusion 主线路径），RESOLUTION 通道跨进程是冒烟首覆盖。
- **依赖**：+langchain-openai>=1.0（pip 实装 1.7.2，openai 3.37 传递带入）。
- **接续**：v1.5 背欠清首项；余项（工具执行回路/decision_mode·skill_packs 图内消费者/AskUserQuestion 本体/…）不变。

**Q65（UX 方向五裁定 + 远端仓，2026-10-25 晚）**：
- **CLI UI = Claude Code 一模一样**：TS 前端（React 19 + Ink）+ Python 后端双运行时确认（用户 Q1/Q2 合并裁定："Windows 观感"仅指 API 配置窗口=tkinter，CLI 本体走 Ink 克隆）。参考资料 claude-code-best/claude-code（23k star 逆向重实现）架构事实：Bun≥1.3 构建/React 19/@anthropic-ai/ink（vendored fork）/marked+cli-highlight+chalk 渲染/**get-east-asian-width 处理 CJK 宽度**（中文 UI 关键依赖）/src+components+screens+keybindings 分区。**License 红线：该仓无 License（全权保留），只学模式不抄代码**；Ink 用 npm 正版（MIT）。
- **问卷重编排定稿**：①"今天要做什么呢？"（开场提示语+自由文本即首条图输入）②build_ways ③"是否需要每轮给出指引帮助更好的理解项目？"（挪到 build_ways 之后）。**user_mode 不再单独问**（用户裁定"指引问题已解决"）：指引答案驱动 guidance 兜底与 actor 提示词语气——推导规则=选"需要/先问"→novice 语气+guidance，"不需要"→experienced（实现时按此落，可否决）。decision_mode → 配置窗口（默认 ai_review）；skill_packs → 默认 ["default"] 交主 agent。
- **配置窗口**：tkinter，字段=主模型/key/base_url/子模型+决策模式开关，**附"测试连接"按钮**（httpx 1-token ping，已在依赖树）。
- **分发**：pipx；命令名 `engine`；远端仓 https://github.com/Iivresse1/engine_agent.git（首推 main=当前版本）。
- **冒烟产物防再污染**：.gitignore +BUILD_LOG.md/NOTES.md（自托管冒烟 workspace_root=cwd 会落盘生成物；2aade20 曾误入 BUILD_LOG.md，c03edf2 amend 清除）。

**Q66（13 票 teach-me + 文案润色，2026-10-25 晚，839 绿零警告）**：
- **teach-me 技能**（用户提案）：ask 模式指引询问真断点化（四选：简短讲解/深度教学/跳过/以后都深度教学——spec L208"ask 档指引询问"本义回填，10 票贴标签实现升级）；选"以后都"写 teach_me_pref=always 后每轮直达；auto 恒普通指引（用户裁定）；HTML 教学页落盘 teach-me/R{n}/index.html（自包含、概念勾选存 localStorage，用户裁定）+ learner-profile.md/session.md 纯代码维护（已掌握概念不重教）。
- **文案全量润色**（用户："可读性非常差，看到会生气"）：全部提问点改"主体 —— 解释"式（DSH 断点风格）；question/choice:build_way payload +explanation 必填；rendering.py 三层渲染（主体加粗，TTY 判定退化）；docs_done 否定词误吞修复（长选项"生成不运行"含"不"字——改整词集合+单字等值判定）。
- **brief 掉落语义钉板**：选"简短讲解"的那一轮走 auto 同款普通指引（guidance_ask_consumed 局部标志防后置重问）——用户已当场决定"要"，再问即骚扰。
- **teach-me 历史考据修正**：claude-code-best 仓的 teach-me/ 目录实测为 markdown 笔记（learner-profile/session/notes），HTML 之说来自社区 codebase-to-course 先例；产物 HTML 形态为用户裁定。无 License 仓只学模式不抄码。
- 实现细节：+43 测试（821→839）；teach_me.py/rendering.py 新模块；spec v1.6 回填（question/choice:build_way +explanation、仪表盘 +teach_me_pref）。

**Q67（14 票 UX-1 壳票，2026-10-25 深夜，854 绿零警告）**：
- **engine 命令落地**（Q65 裁定）：pyproject scripts 只留 engine（旧名 project-agent 废弃）；`--state` 默认改每项目 `<cwd>/.project-agent/state.db`（config 仍全局 `~/.project-agent/config.env`——一次配置任何目录可用，换目录即新会话）。
- **问卷重编排**（Q65 裁定落定）：①"今天要做什么呢？"= REPL 开场提示语（banner 后空行+一行；首条自由文本即图输入——零架构改动）②build_ways ③指引一问挪至 build_ways 决议后。**四问删到一问**：user_mode 由指引答案推导（auto/ask→novice、off→experienced）；decision_mode → 配置窗口（默认 ai_review）；skill_packs → REPL 种子注入默认 ["default"]（首条输入随行、仅无值键生效）。ask_tasks_node 瘦身为"简报直写零 question"；guidance_trigger_node 改造为指引一问的发射/消费/映射三态。
- **tkinter 配置窗口**（gui_config.py 新模块）：主模型/key（mask）/base_url/子模型/决策模式开关（默认开）+ **测试连接按钮**（httpx 1-token ping POST {base}/chat/completions，2xx 即通；不阻塞保存）；分层可测——纯函数层（form_fields_to_config/test_connection MockTransport 注入）12 测试零 GUI；tkinter 壳全异常兜底返 None → cli 退终端问卷 fallback（问卷第五问：决策模式，回车默认 ai_review）。
- **AppConfig +decision_mode**（"ai_review"|"manual"，受控归一）；.env +decision_mode 键（旧文件缺省 → ai_review 向后兼容）。
- **入口路由新行**：task_brief+build_way 已设且 guidance_pref 未设（None/""——**off 是合法已设值，falsy 陷阱两处修正**：entry_route 与 guidance_trigger_node 的"已设"判定都不得用 truthy）→ GUIDANCE_TRIGGER。END_MAP 补 guidance_trigger 键（START 条件边映射缺失会 KeyError——图级测试抓出）。真值表全部后续行样例补 guidance_pref 已设。
- **keyword 否定优先序**："不需要"含"需要"误判 auto——off 词表前置（skill_packs 同法第三例，falsy/子串双陷阱家族）。
- 测试：+18 新测试（gui_config 12 + restructured_flow 6；随四问删除 839→854）；旧测试 128 例批量适配（子代理按五规则分派：KeyError 补种子/旧问卷断言改简报断言/guidance_trigger 三态改写/路由行补字段/config 序列补应答）。spec v1.7 回填（节点读写表/路由真值表/首启两层节）。
- **Q39 红线精化**：gui_config 的 httpx 改惰性导入（`_httpx()` 函数内），兜底扫描豁免该模块（用户主动测试连接非上报路径），并新增"顶层 import httpx 即倒退"哨兵测试（红线从"禁网络库"精化为"禁自动上报 + 禁顶层加载"）。

**Q68（spec v2.0 回灌 + 文档纪律，2026-10-26 凌晨，用户指令）**：用户指出"倒数十轮的新想法没有重新进 spec，项目文档都没改动就开工，那不是没改动吗"——裁定**冲突以新为准**，要求把这十轮的裁定全部补充入 spec。核对结果：spec 停在 v1.7，Q64 真模型接线、Q65 UX 五裁定、Q66 teach-me、Q67 壳票**全部未入文档**，且正文有 4 处与新发展正面冲突（"v1 全 CLI""Web UI/前端已砍""rich/textual 后置""项目级四问"）。
- **spec 升 v2.0（重写而非打补丁）**：版本志补齐 v1.5/v1.6/v1.7/v1.8/v2.0 五行（此前 v1.5 的回填做了但版本志漏记，版本号从 v1.4 直接跳到 v1.6）；正文按现状态重写——总体架构改双运行时、新增"运行时与配置（v1.8 真模型接线）"节、图拓扑改**相位图**（每轮单相位 + END，纠正原文"一轮跑完整个流程"的错误表述）、仪表盘写者列按 Q65/Q67 改口（user_mode←guidance_trigger 推导、decision_mode←配置窗口+种子、skill_packs←种子+`/skills`）、新增"指引与教学通道""文案可读性契约""外观与分发""工程护栏""已知欠账"五节。
- **冲突作废显式记档**：Out of Scope 中三条旧条目划线并标注"v2.0 作废"（v1 全 CLI / Web UI 已砍 / rich-textual 后置）——**不静默删除**，保留演化痕迹。
- **新增"已知欠账"节**：初版 16 行（契约审计后扩至 20 行），把"设计已定、实现未落地"的差额集中记账（工具执行回路、decision_mode/skill_packs 图内消费者、AskUserQuestion 本体、TodoWrite key、旁路持久化、current_scope 写者、verify_link、final_report 注入、ask 档内容循环、压缩挂点、官方 Store、前端 UX-2/UX-3、guidance_read_version 门归属、planner 模板覆盖、nodes.py 拆分；审计后补 `/teach-me off`、桌面密钥读取、SkillRecommend 本体、技能包两级）。**纪律**：spec 与代码不一致只允许出现在此表——否则即缺陷。
- **新纪律（治本次根因）**：**新裁定先入 spec/GLOSSARY 再开票**。票面只做"由 spec 到代码"的翻译，不做新设计；spec 未回填就开工 = 流程违规，与"表即契约"同级。
- **ADR-0005 新立**：双运行时（TS+React19+Ink 前端 / Python 后端，只经协议消息对话）；接缝预算钉死为只新增"前端↔后端"一条；许可红线（无 License 仓只学模式不抄码）；tkinter 仍仅配置窗口；过渡态=后端可裸终端运行。
- **GLOSSARY 增补九条**：前端 / 后端 / 双运行时 / teach-me（深度教学）/ 讲解 / 四选 / 可读性契约 / 配置窗口 / 测试连接 / 种子注入 / engine——并把"REPL 宿主"词条限定为**后端**侧（原文 _Avoid_ "前端" 与新概念冲突，靠精确化消解而非删除）。术语哨兵不受影响（新增词条均非 _Avoid_ 单词）。
- **台账自身修正**：挂起项"Q15 CLI 框架 / Q16 后端形态 / CLI 界面细节（后置）"划掉并标注由 Q65 裁定，剩余差额指向 spec 欠账表——避免台账与 spec 两处都停在旧状态。

**Q69（UX-2 第一片：协议消息层落地，2026-10-26 凌晨，用户指令"先确认 todo 与新想法对齐，然后实现，做到凌晨 1 点后备份"）**：按 Q68 纪律执行——**先 spec 再代码**，本轮只做协议契约与翻译层，不碰前端。
- **spec 升 v2.1**：新增『协议消息层（UX-2 契约）』节——6 类下行（ready/prompt/round_end/notice/teach_page/farewell）+ 2 类上行（input/quit）消息表 + 四条硬约束（信封只一层 / 后端裸终端仍可用 / 协议层零业务逻辑 / 决议语义仍走自由文本）；测试决策表新增"协议消息层"行；欠账表把"前端（UX-2/UX-3）"一行拆成"前端传输层（余下）"与"前端界面（UX-3）"两行。
- **messages.py 新模块**（纯翻译层）：`MessageSpec` 表 + `encode`（下行构造，缺/多/错类型 → `MessageError`）+ `decode`（上行校验，`type` 查表一次完成）+ `default_rendering`（六类下行折叠终端行）+ `round_end_message` 便捷构造。**红线**：不 import 任何图/节点/模型/REPL/langgraph 模块，AST 哨兵强制。
- **REPL 三处接线**（开场 ready / 轮终 round_end / 退出 EOF farewell）：终端行为逐字不变（旧断言全绿），但渲染路径已是协议层折叠——即"兼容降级"的落地形态，前端接入时零图改动。
- **冒烟发现并修一处真缺陷**：`choice:build_way` / `choice:proposal` / `docs_done` 断点此前**整 dict 平铺**，未走 spec『文案可读性契约』的三层渲染。新增 `rendering.render_breakpoint_lines(reason, payload)` 作唯一分发点（question → 三层问题；决议类 → 主体/解释/编号选项/`推荐：`+独立`推荐理由：`行；其余平铺）。**理由必须独立成行**——推荐串自带" —— "说明时仍保留 ≤20 字代码截断理由，否则"推荐必附理由"会被内嵌说明吞掉。
- **GLOSSARY 增补两条**：协议消息 / 终端降级渲染（后者明确"不是简化模式，是与前端平行的第二个消费者"）；术语哨兵绿。
- **票**：15 票（UX-2 第一片）标 done，含验收测试清单与禁改清单；16 票（UX-3 传输+前端+Bun）开为 ready，列 5 片切片计划与**3 个必须先裁的点**（端口发现 / 产物分发 / 断线恢复语义）——未裁前不得实现。
- 测试 881 → 882（+26 新，摊薄后净增 28；3 例旧 REPL 断言随渲染升级适配）；ruff 干净、零警告。

**Q70（契约审计修正：spec 与代码直冲突清账，2026-10-26 00:57）**：子代理对 spec/GLOSSARY/ADR/票面做只读契约审计，报 16 条 spec 本体缺陷 + 9 项未入 spec 裁定 + 票面差额 + GLOSSARY 缺口。**逐项对照代码核实后确认 3 条为"表与代码直冲突"（按 Q68 纪律即缺陷）**，当场修：
- **A4 修正（spec 写反）**：原文写 actor "用 `@dynamic_prompt` / `wrap_model_call` 中间件送达"——09 票已终裁**弃用 langchain middleware**（1.x 版本敏感），代码走 assembler 装入 + actor 读 assembled_context 写 system。spec 改为"不用 langchain middleware；工具清单由 actor system 尾行送达"。
- **A5 修正（物理不可能）**：压缩挂点原列 `planner`——planner 是纯代码零 LLM 调用（nodes.py docstring 明说"planner 无 LLM 调用不挂"）。改为**四挂点**：assembler / actor / verifier / demo_agent。
- **A3 修正（自相矛盾）**：正文两处写旁路"独立 checkpointer 记录"，欠账表写"历史未落盘重启即失"——代码 AskBypass 只建 thread 后缀、无落盘。两处正文改为"独立 thread、**历史暂未落盘**（见欠账）"。
- **A1**：来源行与 Further Notes 统一 Q1–Q69。**A2**：轮的机械化表述改为"一轮 = 一次 invoke、跑一个相位簇"（相位制 Q61），与图拓扑节口径统一。**A6**：Actor 工厂改"4 × 2（`guidance_enabled`）"，指引三态分流归后置工序。**A7**：demo_phase 形状改"未设/building/skipped/done"（代码 `_after_docs_done` 认 done）。**A8**：真值表 ≥5 与断点协议 =5 统一为 **≥5**（含图拓扑表三处）。**A9**：集成分支缺 LICENSE（main 有）——已 `git checkout main -- LICENSE` 恢复，spec 改口"仓库根 LICENSE 已入集成分支"。
- **A10/A11**：用户故事 28/29 加"当前未接线，见欠账"；故事 35 由"侧栏/折叠面板"降级为"独立段落"（代码无侧栏）。**A12**：路由节补 CLI 旗标（`--state` / `--config` / `--new-session`）。**A13**：补**交付物集定义表**（way1 无 / way2 IDEA.md / way3 三件 / way4 六件）。**A16**：权限矩阵补 `DocScaffold`，并注明 `SkillRecommend`/`AskUserQuestion` 仅声明无本体。
- **B 节裁定补入**：Q9/Q10 技能包两级（包 vs 技能、启动选包、完整 Matt Pocock 包、模拟全文桩现状）写进"技能懒加载"并落欠账；Q35 `/ask-for-help` 前置条件补入路由节。
- **欠账表 16 → 20 行**：新增 `/teach-me off` 恢复路径（双缺）、桌面密钥读取（Q64 用户明示但代码无此路径）、SkillRecommend 本体、技能包两级。
- **GLOSSARY 三处矛盾修正**：teach-me 词条"三选形态"→"ask 档四选之一（指引三态是另一维度）"；AskAgent 双通道词条补"teach-me 是图内通道第三形态"；REPL 宿主"终端 I/O"→"协议服务"，终端 I/O 降级为过渡态出口。**新增 6 词条**：相位 / 相位图 / 表即契约 / 首启两层 / 本地账单 / 技能包 / 学习者画像。
- **台账自身**：Q47 挂起项划掉（Q47 早已终裁不做，台账 stale）；欠账行数记账更新。
- 验证：spec 500 行 / 75 用户故事 / 20 行欠账 / 表格全闭合；GLOSSARY 词条 43 → 49 且哨兵绿；882 测试全绿、ruff 干净。
- **未修（留待用户裁）**：D 节建议的三份 ADR（文案可读性契约 / 配置格式 / 单题问卷）——属"补决策记录"而非冲突，不擅立；13 票 C 节问卷文案表被 14 票整表替换但票面未改口（票面 stale，需重写票 13 或加作废标记）。

**Q71（UX-2 传输三裁 + 片 1 落地，2026-10-26 上午，用户裁定）**：用户对票 16 预留的三个待裁点一口气裁定，按 Q68 纪律**先回填 spec v2.2 再动代码**。
- **三裁**：①**随机端口 + 握手文件**——后端 bind `127.0.0.1:0` 由 OS 分配，`{pid, port, thread_id, protocol_version, started_at}` 原子写入 `<cwd>/.project-agent/handshake.json`；前端读文件连接，不固定端口（避免撞端口与多项目并行冲突）。②**前端产物首次运行下载**——wheel 保持纯 Python 不打包前端，首次运行下载到 `~/.project-agent/frontend/<version>/` 并校验；失败/拒绝 → 退终端降级渲染。③**断线复用 thread_id 续跑**——重连带握手文件的 thread_id，同 checkpointer 同 thread，末态由 `_seed_state_from_checkpoint` 重建；不新开会话，显式放弃走 `--new-session`。
- **spec v2.2**：新增『传输层（UX-2 第二片）』节承载三裁 + 三条硬约束；版本志补 v2.2；来源行与 Further Notes 统一 Q1–Q71；欠账表"前端传输层"行改口为"v2.2 开做（三裁已定）"。**顺带修掉版本志顺序错误**（v2.1 曾排在 v2.0 之上）。
- **repl.py 结构改动（本片唯一）**：新增 `_emit`（下行消息 → 终端降级渲染 + 可选收集）/ `_notice`（即时提示）/ `begin_collect` / **`handle_input(text) -> list[dict]`**；22 处 `_io.write_line` 直写全部改走 `_notice`，轮终交付改走 `_emit(round_end_message(...))`。**终端行为逐字不变**（882 旧测试全绿为判据），而 WebSocket 拿到的是同一份结构化消息——两个消费者共用一条实现，不是两套逻辑。
- **transport.py 新模块**：`Handshake` 数据类 + `write_handshake`（**原子写**：临时文件 + `os.replace`，防前端读到半截 JSON）/ `read_handshake`（六字段校验，bool 冒充 int 拦）/ `clear_handshake` / `is_stale`（pid 存活判定）/ `new_handshake` / `ProtocolServer`（收上行 JSON → `decode` 校验 → 分发；坏 JSON 或不合协议回 `notice` 而非崩溃）/ `is_quit` / `make_serve`（**延迟 import websockets**，顶层不引网络库——Q39 红线同法）/ `_bound_port`（从 Server.sockets 取实际端口，版本形态兜底）。
- **测试 882 → 906（+24）**：握手文件往返/原子写/父目录/损坏/缺字段/bool 冒充/清理幂等/陈废三态；上行分发五路（正常 input、quit、坏 JSON、未知 type、缺字段）；`is_quit`；**真实 WebSocket 端到端**（临时目录起服务 → 等握手文件 → 读端口 → 真连 → input 收 notice → 撤销 → 断言握手文件被清理）；两条 AST 红线哨兵（不依赖图/模型；顶层不 import websockets）。
- **依赖**：`websockets>=12` 补进 pyproject `dependencies`（venv 中原已存在但从未声明——本身是一处欠账，现已补）。
- **冒烟（真实链路）**：起服务 → 握手文件 `pid=24200 port=51296 thread=t-smoke v1` → 陈废判定 False → 连上后「我想做一个记账 CLI」收到 `round_end`（含结构化 payload 与 `lines`）→「嗯」收到 `round_end` → `quit` 收到 `farewell` → 握手文件已清理；同时终端路径七项断言全绿。
- **票 16 改为 in_progress**：三裁从"未定需先裁"挪到"已裁三点"，片 1 标记为本片；片 4 改为"产物下载与 engine 并联"。
- 未做（后续片）：前端 Ink 骨架（片 2）、面板按键（片 3）、产物下载与 engine 并联（片 4）、收口（片 5）。

**Q71 续（UX-3 片 2：Ink 前端骨架落地，2026-10-26 上午）**：片 1 提交后直接做片 2，前后端真实联调跑通。
- **`frontend/` 新目录**（TS + React 19 + Ink 8 + ws，Node v24）：`src/protocol.ts`（六类下行解析，形状严格镜像后端 `messages.py`，**数组不得冒充对象**）/ `src/handshake.ts`（随机端口发现：六字段解析、pid 存活、协议版本兼容）/ `src/client.ts`（WebSocket 连接与消息桥）/ `src/width.ts`（东亚字宽，**显式禁用 String.length**）/ `src/App.tsx`（渲染队列 + 按键采集，不持有业务状态）/ `src/main.tsx`（入口，连不上即降级提示）。
- **职责边界的代码化**：前端拿到 `round_end` 直接绘制后端给的 `lines`，**不重排文案**——否则两处文案必然漂移（spec『文案可读性契约』的跨端推论）。
- **测试 12 例（vitest）**：协议解析 6（六类下行、坏 JSON、未知 type、缺字段、lines 含非串、payload 为数组）+ 握手 4（往返、缺字段、版本兼容、pid 存活）+ 字宽 2（全角 2 列、length 与显示宽度不等哨兵）。
- **修掉一处真缺陷（造红转绿）**：`parseDownMessage` 对 `payload: []` 曾经放行（`typeof [] === "object"`），与后端 `MessageError` 的严格性不一致；补 `Array.isArray` 拒绝后转绿。
- **真实联调冒烟**：后端起在**随机端口 57297**（握手文件 `thread=t-frontend`）→ 前端读握手文件发现并连上 → `input → round_end → choice:build_way → farewell` 全通；终端路径同时保持八项断言全绿。
- **工具链事实**：本机无 `bun`、无全局 `pnpm`；用 DSH 提供的 node/pnpm 路径（`pnpm.mjs`）。`pnpm run typecheck/build` 会被 esbuild 构建审批阻断，改用 `node node_modules/typescript/bin/tsc` 直接调用（已在 `package.json` 加 `pnpm.onlyBuiltDependencies` 白名单）。`vitest --reporter=basic` 在 vitest 5 下不可用，改默认 reporter。
- **`.gitignore` 补**：`frontend/node_modules/`、`frontend/dist/` 不入库；锁文件 `pnpm-lock.yaml` 入库保证可复现。
- **未做**：片 3（面板/按键细化）、片 4（产物下载 + engine 并联）、片 5（收口）。

**Q71 再续（UX-3 片 3：面板与按键，2026-10-26 中午）**：前端从"能收发"推进到"能看"。
- **常驻按键提示行**：`Enter 提交 · Ctrl+O 状态面板 · Ctrl+T 教学页 · Esc 退出`（观感对齐 Claude Code 的按键提示惯例）。
- **状态面板（Ctrl+O 折叠）**：显示最近 `task_brief:` 状态行 + 最近断点（reason 与行数）。**前端不解析 Dashboard**——只显示 `/status` 的 notice 文本，业务状态仍在后端。
- **教学页面板（Ctrl+T 折叠）**：显示路径与轮次；**前端不内联渲染 HTML**，只提示用浏览器打开（teach-me 页是自包含单文件，归浏览器）。
- **可测性重构（本片真正的技术收获）**：把纯展示部分抽成 `TranscriptView`（**无 hooks、无副作用**），用 ink `renderToString` 做真实渲染断言 6 例；`toEntries` 导出为纯函数，面板取数直接测**真实实现**而非镜像副本（镜像必漂移）；`subscribe` 改为 **prop 注入**（去掉全局单例依赖），组件与测试都更干净。
- **三条形态事实（踩过才知道）**：① Ink 8 无 `lastFrame`；② `renderToString` 不跑 effect，故**只有纯组件可做渲染断言**；③ Windows 无 `pty`/`termios`，PTY 抓帧不可用。这三点合起来使"纯视图 + renderToString"成为唯一可靠的渲染测试路径。
- 测试：前端 12 → **26**（+6 渲染 +8 面板取数；原 5 例镜像测试重写为测真实实现）。
- **未做**：片 4（产物下载 + engine 并联）、片 5（收口）。

**Q71 三续（UX-3 片 4：产物分发 + engine 并联，2026-10-26 中午）**：双运行时从"能跑"到"单命令可用"。
- **`frontend_launcher.py`**（纯逻辑，网络经 `fetch` 注入 → 测试零网络）：`ensure_frontend` 查找顺序 = **已安装目录 → 开发态 `frontend/` → 下载安装到 `~/.project-agent/frontend/<version>/`**；`_extract` 支持 zip/tar，**拒绝对路径、盘符、`..` 穿越**；`frontend_url` 从环境变量 `PROJECT_AGENT_FRONTEND_URL` 取（不硬编码不存在的 URL）；**任何失败一律返回 None**——降级优先于报错。
- **`engine` 并联**：新增 `--no-ui` / `--ui`；默认尝试前端。`_launch_frontend` 先**探活**（非 TTY 下前端退码 2）→ 通过则以 `Popen` 交接，后端转协议服务（`make_serve` + `asyncio.run`）；不通过 → 裸终端 REPL。
- **两处真缺陷（造红转绿）**：① `_extract` 的穿越检查**漏掉绝对路径**——Windows 上 `Path("/abs/x").is_absolute()` 为 False 且 zipfile 不规范化开头 `/`，改用显式前缀 + 盘符 + `..` 三重检查；② 前端在**非 TTY** 直接崩栈（Ink "Raw mode is not supported"）——入口先判 `canRenderInk()`（isTTY 且 setRawMode 可调用），不支持则以**码 2** 退出并说明，`engine` 据码 2 回落。
- **红线哨兵自身缺陷修复**：`test_no_network_reporting` 原用 `ast.walk` 扫全文件，却标注"顶层零网络 import"——语义与实现不符（此前靠给 `gui_config.py` 整文件豁免绕过）。本轮改为**只扫模块顶层**（函数内惰性导入不算），把 `frontend_launcher.py` 加入惰性集合并加"顶层出现即倒退"断言。**这是修哨兵不是放宽标准**：顶层 import = 进程启动即有外发能力，函数内惰性导入 = 用户主动动作才发生，二者语义本就不同。
- **测试 906 → 928（+22）**：启动器 21（布局/发现顺序/URL 解析/下载安装/带顶层目录的 tar/下载失败/空载荷/缺入口/穿越拒绝/格式拒绝/两条红线）+ 哨兵语义测试。前端 26 → 30（+4 入口降级判定）。
- **联调验证**：`--no-ui` 裸终端正常（开场三行 + 再见，码 0）；`--ui` 非 TTY 下探活得码 2 → 回落裸终端、零崩溃；开发态产物发现命中 `frontend/dist/main.js`。
- **未做**：片 5（收口：合并、全量、勾票）。

**Q71 收口（UX-3 全票完成，2026-10-26 12:05）**：16 票五片全部落地，**双运行时从"已裁定"变成"可用"**。
- **收口数据**：后端 928 passed（本票 +46）、前端 30 passed、前端 `tsc --noEmit` 零错、ruff All checks passed。
- **禁改清单核对**：`nodes.py`/`graph.py`/`routing.py`/`protocol.py`/`messages.py` 相对本票起点 `cf5e2e3` **零改动**（`git diff --stat` 无输出）——接缝预算（只新增"前端↔后端"一条）与实际改动一致，图与协议表没被前端需求污染。
- **可用形态**：`engine` 默认拉起 Ink 前端 + 后端转协议服务；无 Node / 无产物 / 非 TTY / 用户 `--no-ui` → **自动退裸终端，零崩溃**（降级优先于报错）。
- **票面 `16-ux3-frontend-and-transport.md` 勾为 done**，含收口结论表与"后续未做"（真实发布源 URL 与产物上传流水线——`PROJECT_AGENT_FRONTEND_URL` 未配时一律退终端，功能安全）。
- **spec v2.2 版本志改口**为"传输层、Ink 骨架、面板按键、产物分发与 engine 并联全部落地——双运行时完整可用"；欠账表"前端界面（UX-3）"行改为"片 1–4 已落，仅余片 5 收口"。
- **流程复盘（对 Q68 纪律的验证）**："先 spec 再代码"在本票执行到位——三裁先入 spec v2.2 再动 `transport.py`；每片一次提交、每片跑全量；两处真缺陷（路径穿越漏判、非 TTY 崩栈）都是**冒烟/测试先红后修**，无一处"写完即认为对"。

**Q72（17 票：工具执行回路，2026-10-26 中午，用户"继续完成剩余任务"）**：最大一块欠账落地——**actor 从文本指令桥升级为真实工具调用环**。按 Q68 纪律先回填 spec v2.3 再动代码。
- **spec v2.3 新增『工具执行回路』节**：五道工序（定义 → 调模型 → 判定 → 执行 → 回灌）+ 封顶 8 次 + 工具实现表 + 三条硬约束（权限在构造期 / 工具错误不中断环 / 文本桥不删）。
- **`tools/file_tools.py`（新）**：六件本体 FileRead/Glob/Grep/FileWrite/FileEdit/DocScaffold。**路径三重检查**（绝对路径前缀、盘符、`..` 片段 + resolve 后越界再查一次，与 `frontend_launcher` 同法）。FileEdit 要求 `old` **恰好命中一次**（0 次或多处都报错，不猜不批量）；DocScaffold 已存在则跳过（不覆盖用户内容）；FileRead 剥 BOM、带行号、支持 offset/limit。
- **`tools/tool_loop.py`（新）**：`tool_definitions(role)` 只产出面内工具 schema（**构造期强制**，模型看不到面外工具）；`ToolLoop` 编排五次工序，`registry.check` 是第二道（防幻觉造工具名）；deny/异常/超限**一律折成 tool 消息回灌**——这是"agent 对话节律"的要求。`LoopOutcome.summary` 产出用户可见的一行回执。
- **`model_client.py` 扩展**：新增 `ToolCall` / `ToolAwareResult` / `ToolAwareModelClient` / `supports_tools`（`hasattr` 探测——Protocol 表达不了"可选方法"，而这样既有桩模型零改动即通过）。**兼容红线**：无工具能力的模型走原单发路径，行为与 05/07 票逐字一致。
- **`openai_client.py` 扩展**：`complete_with_tools` 用 langchain `bind_tools`（每请求绑定，不改客户端构造态），真实模型可走工具环。
- **`nodes.py` 接线**：两个 body 统一走 `_run_actor_with_tools`；新增 `_actor_tool_runner`——文件工具走 `file_execute`，`Shell` 走**真实 subprocess 执行**（已过 `ShellPolicy` 静态正则 + 两旋钮 + 审批回调）。
- **顺带清掉一条欠账**：`decision_mode` 的**第一个图内消费者**——`knobs.from_decision_mode` 接 `ShellTool`。图内无交互通道，故 `manual` 档一律拒（fail-closed），`ai_review` 档静态放行的可执行。
- **三处真缺陷（全部造红转绿）**：① `ShellPolicy` 构造缺 `knobs`/`workspace_root` 两参；② **成败靠字符串前缀猜** —— `ToolLoop._invoke` 把 `Shell` 返回的字符串一律当成功，Shell 被拒的 `ok=False` 被吞掉，改为 runner **统一返回 ToolResult**、成败由 `ok` 字段决定；③ **`manual` 档静默失效** —— `knobs._DECISION_MODE_MAP` 只认 `human`，而 `config.py` 的 `decision_mode` 词表是 `ai_review|manual`，`manual` 被当未识别回落 `ai_review`（**等于人工确认档形同虚设**），按 `config.py` 词表补齐 `"manual"` 映射到 `Interrupt.HUMAN`。
- **术语哨兵拦下一次违规**：`nodes.py` 里写了 `knobs.interrupt` —— GLOSSARY 把 `interrupt` 列为 `_Avoid_` 标识符，豁免只覆盖 `tools/` 子树（Q23 两旋钮术语）。不改哨兵、不改豁免，而是在 `knobs` 上加 `ask_level()` 返回字符串档位，调用方按字符串比较——**符合规则的正解**。
- **测试 983 → 989（+55 净增，摊薄后 +6）**：tool_loop 48 + actor 接线 7 + decision_mode 6。
- **真实冒烟**：模拟多步模型 → 4 次工具调用（DocScaffold → FileWrite → Glob → Shell）→ 磁盘真实出现 README.md/TODO.md/目录树.txt（内容为工具所写）→ shell 真实执行 `echo tool-loop-works` → 终稿带"工具调用 4 次（成功 4）"回执。
- **未做（记欠账）**：`AskUserQuestion` 与 `SkillRecommend` 工具本体、`NotepadAdd` 接入工具环分派、`skill_packs` 选包注入。

- Q39 token 按 agent 记账落地（= harness Observe 模块的具体化）
- Q48–Q52（上下文工程层边界问题，已摆）
- ~~Q47 archify 渲染交互式架构图（待图定稿）~~ → **已裁不做**（Q47 终裁：终稿图以简图形式交付；spec 未承诺该能力，台账此前 stale）
- ~~Q15 CLI 框架 / Q16 后端形态 / CLI 界面细节（后置）~~ → **已由 Q65 裁定**（CLI 框架 = React 19 + Ink；后端形态 = Python 后端 + 双运行时 ADR-0005；界面细节 = 观感对齐 Claude Code）。剩余未落地部分转 spec「已知欠账」表的"前端传输层（UX-2 余下）/ 前端界面（UX-3）"两行。

## 事实核查基准

见 `docs/research/langgraph-verification-2026.md`（LangGraph 1.x，2026-10）。
关键结论：Store 跨线程共享 ✅ / thread_id 隔离 ✅ / subagents-as-tools 思考隔离 ✅ / interrupt+Command(resume) 持久等待 ✅ / 按 agent token 记账需自建 ⚠️ / langgraph-supervisor 已停维护（自行组装路由）⚠️
