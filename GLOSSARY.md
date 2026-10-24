# 项目构建 Agent（Project Agent）

一个 CLI 形态的 LangGraph 应用：用户丢进一个想法，agent 通过 grilling 式问答增量构建项目文档，期间可随时旁路提问学习，最终可生成 demo。核心动机是"构建与学习并行、上下文互不污染、token 花在刀刃上"。

## Language

### 会话与控制流

**断点 (Breakpoint)**:
一轮执行的自然终点——图跑完本轮、状态落盘、控制权交还 REPL，等待用户下一条自由 prompt 融合同线程续跑。
_Avoid_: interrupt、暂停、断点续传

**轮次 (Round)**:
两个断点之间的一次完整图执行；所有生成物以轮次为溯源单位。
_Avoid_: 回合、turn、对话轮

**【R#】标记 (Round Marker)**:
挂在每轮生成物前的轮次标注，构建期供子角色按轮切片检索，终检时剥离。
_Avoid_: 轮次前缀、tag、时间戳

**报错回传 (Error Return)**:
用户把 demo 运行报错粘贴回 REPL，路由进 DemoAgent 调试循环的机制。
_Avoid_: 报错重试、错误注入

**混合路由 (Hybrid Routing)**:
REPL 的三层输入分发：显式斜杠命令 → 报错特征规则预筛 → LLM 窄分类兜底。
_Avoid_: 智能路由、自动分发

### 角色与图

**Actor**:
主工作流图中参数化的执行者节点，由构建方式与指引偏好组合配置；消息历史私有。
_Avoid_: agent（泛称）、worker、子agent

**REPL 宿主 (REPL Host)**:
应用外壳层——终端 I/O、斜杠路由、断点持有、shell 审批回调、本地账单。
_Avoid_: 前端、壳层、CLI框架

**主工作流图 (Main Workflow Graph)**:
从 ask_tasks 到 FINISH 的单一大图，含 planner→actor→verifier 主环。
_Avoid_: 超级图、pipeline、工作流引擎

**verifier**:
轮间检查闸门——LLM 判断产出质量并置位 gate 变量，路由由纯代码完成。
_Avoid_: Verifier（参考架构里验代码的那个，语义不同）

**check_proper_output**:
终点质检管线——剥【R#】标记、按构建方式对账文档集、双份交付（备份版+干净版）。
_Avoid_: Finalizer（那是收尾整理节点，不是质检）

**gate 变量 (Gate Variable)**:
state 中由 verifier 置位、由条件边消费的布尔组；体现"LLM 判内容，代码管路由"。
_Avoid_: flag、状态位、开关

### 构建方式

**build_ways（构建方式）**:
入口四选一：对话 / 轻 grill / 简化文档 / 完整文档。
_Avoid_: 档位、tier、模式

**决策模式 (Decision Mode)**:
shell 审批的档位——AI 自动审核 / 全权人工；对应两旋钮中的 interrupt 旋钮初值。
_Avoid_: 权限模式、permission mode

**三方案并行**:
完整文档方式专属：grilling 到位后并行生成三套方案，断点处由用户选定。
_Avoid_: 多方案对比、头脑风暴

### 上下文工程

**Context Assembler（上下文组装器）**:
轮始决定"装什么"进本轮上下文的图节点——规则文件、todo 板、notepad 切片、工具子集声明写入 state。
_Avoid_: prompt 拼接器、注入器

**Notepad**:
工作区共享的外部记忆文件——错误猜想与关键事实的条目库，全角色可读写，条目带【R#】。
_Avoid_: 笔记本、memory、缓存

**头部单包 (Head Memory Pack)**:
压缩产出的合并记忆区，按序驻留消息历史头部，每包首行标注覆盖轮次。
_Avoid_: 摘要列表、压缩缓存

**作用域 (Scope)**:
当前工作区域的声明——决定加载哪份规则文件、裁剪哪套工具子集。
_Avoid_: 上下文切换、目录模式

**final_report**:
会话终点写入长期记忆库的成果变量，供未来新会话检索注入。
_Avoid_: 总结、会话记录

### 隔离与共享

**隔离红线 (Isolation Red Line)**:
各角色消息历史永不进入彼此上下文；跨角色信息只通过共享文档区交换。
_Avoid_: 隔离机制（泛称）、防火墙

**共享文档区 (Shared Docs)**:
隔离红线下唯一合法的跨角色介质——磁盘上的项目文档与 Notepad。
_Avoid_: 共享上下文、shared state

**仪表盘 (Dashboard)**:
主图全局 state 的定位——只收受控字段（gate/版本号/轮次摘要），不是聊天记录汇总。
_Avoid_: 全局上下文、黑板、黑板板

**AskAgent 双通道**:
AskAgent 的两条调用路径——REPL 旁路直答（拉式问答）与图内新手指引注入（推式教学）。
_Avoid_: 双agent、分身

### 工具与权限

**权限矩阵 (Permission Matrix)**:
各角色可用工具的白名单表，代码层强制、构造期预注册；作用域只能在矩阵内做子集裁剪。
_Avoid_: ACL、工具配置

**静态正则检查器**:
凌驾于白名单与两旋钮之上的 shell 形态学检查——deny 类全档生效，allow 命中也照拦。
_Avoid_: 过滤器、拦截器

**两旋钮 (Two Knobs)**:
shell 权限的两个正交档位——boundary（能碰多大）× interrupt（问不问你）。
_Avoid_: 权限模式（单数）、沙箱档位

**技能懒加载 (Skill Lazy-loading)**:
上下文只注入技能名+一句话描述，SKILL.md 全文在被触发时才读入。
_Avoid_: 预加载、全量注入

**交付物 (Deliverables)**:
交付给用户的项目文档包——docs、目录树、配置、README、TODO。
_Avoid_: 产出物（泛）、文件（泛）

**TodoWrite 工具**:
角色私有的三态计划面板（pending/in_progress/completed），不落盘不共享。
_Avoid_: todo list、任务清单（易与交付物 TODO.md 混淆——后者是 Builder 独占写权的项目文档）
