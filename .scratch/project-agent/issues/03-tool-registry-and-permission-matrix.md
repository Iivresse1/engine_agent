# 03: 工具注册表与权限矩阵

**What to build:** 构造期权限注册表（代码层强制，LLM 不可越权）：Builder / DemoAgent / way1 Actor = 全工具；AskAgent = 只读四件 + 联网两件 + AskUserQuestion + SkillRecommend + NotepadAdd；交付物 TODO.md 写权 Builder 独占；排除清单（AgentTool/SkillTool/Plan Mode 两件/Task* 六件/SendMessage/NotebookEdit/MCP/LSP）生效。shell 侧：静态正则检查器 8 类形态学（灾难删除/下载即执行/提权/凭证/git 不可逆/网络出口/重定向/命令替换——独立于白名单，deny 全档生效含 yolo，allow 命中也拦）+ 两旋钮（boundary × interrupt，决策模式 = interrupt 初值）+ 复合命令拆段 + wrapper 剥离 + 解析失败 = ask（fail-closed）+ Windows rm 与 Remove-Item 别名双拦。shell 审批走 REPL 宿主层同步审批回调（图外，ADR-0001 唯一例外，不落 turn_end_reason 不进图）。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 角色工具集在构造期固定；越权调用结构性不可能（测试断言 AskAgent 工具面内无 FileWrite/FileEdit/Shell）
- [ ] 8 类正则逐类拦截表驱动测试绿；allow 命中 deny 类照样拦；yolo 档 deny 类仍拦
- [ ] 复合命令拆段后逐段判权；wrapper 剥离后再判；解析失败 fail-closed = ask
- [ ] Windows：rm 与 Remove-Item 都被灾难删除类命中
- [ ] 两旋钮组合矩阵（boundary 3 × interrupt 3）表驱动绿；决策模式作为 interrupt 初值
- [ ] 假 shell 记录调用 + 预置输出；拒绝路径不产生副作用
- [ ] 审批走 REPL 同步回调，不产生图内断点
