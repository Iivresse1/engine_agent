# 03: 工具注册表与权限矩阵

**What to build:** 构造期权限注册表（代码层强制，LLM 不可越权）：Builder / DemoAgent / way1 Actor = 全工具；AskAgent = 只读四件 + 联网两件 + AskUserQuestion + SkillRecommend + NotepadAdd；交付物 TODO.md 写权 Builder 独占；排除清单（AgentTool/SkillTool/Plan Mode 两件/Task* 六件/SendMessage/NotebookEdit/MCP/LSP）生效。shell 侧：静态正则检查器 8 类形态学（灾难删除/下载即执行/提权/凭证/git 不可逆/网络出口/重定向/命令替换——独立于白名单，deny 全档生效含 yolo，allow 命中也拦）+ 两旋钮（boundary × interrupt，决策模式 = interrupt 初值）+ 复合命令拆段 + wrapper 剥离 + 解析失败 = ask（fail-closed）+ Windows rm 与 Remove-Item 别名双拦。shell 审批走 REPL 宿主层同步审批回调（图外，ADR-0001 唯一例外，不落 turn_end_reason 不进图）。

**Blocked by:** 01

**Status:** done (2026-10-25)

- [x] 角色工具集在构造期固定；越权调用结构性不可能（测试断言 AskAgent 工具面内无 FileWrite/FileEdit/Shell）——tests/test_tool_registry.py
- [x] 8 类正则逐类拦截表驱动测试绿；allow 命中 deny 类照样拦；yolo 档 deny 类仍拦——tests/test_static_checker.py
- [x] 复合命令拆段后逐段判权；wrapper 剥离后再判；解析失败 fail-closed = ask——tests/test_shell_policy.py
- [x] Windows：rm 与 Remove-Item 都被灾难删除类命中——test_catastrophic_delete_windows_dual_block
- [x] 两旋钮组合矩阵（boundary 3 × interrupt 3）表驱动绿；决策模式作为 interrupt 初值——test_two_knob_matrix（54 例）+ test_knobs.py
- [x] 假 shell 记录调用 + 预置输出；拒绝路径不产生副作用——tests/test_shell_tool.py（RecordingShell 复用 tests/doubles）
- [x] 审批走 REPL 同步回调，不产生图内断点——test_no_graph_layer_imports（AST 钉死 shell_tool/approval 不 import langgraph/graph/nodes/protocol/repl）

## Comments

**2026-10-25 实现 完成（implementer 子代理，合并 e59f1fe，219 绿）**：新包 src/project_agent/tools/（decision/registry/knobs/static_checker/shell_policy+json/approval/shell_tool 七模块）。TDD 红阶段抓到 4 个真 bug（`/` 被当 flag 跳过致 rm -rf / 漏拦 / 裸命令匹配序错 / yolo 覆写白名单 rule_id / 空段集聚合被默认 ask 压过）。内联脚本删除扫描为设计增强（bash -c 'rm -rf ~' / node -e "rm -rf /" 也命中类 1）。fail-closed 误伤清单（引号内敏感词 / --force 含 r / PowerShell 反引号）文档化于模块 docstring 属预期。main 包接线（ShellTool 挂入图/角色装配）属后续票。**纪律注记**：implementer 自行更新了票面勾选（应 Lead 收口）——内容经 Lead 核验无误后接受。
