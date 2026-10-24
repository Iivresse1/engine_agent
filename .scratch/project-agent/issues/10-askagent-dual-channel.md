# 10: AskAgent 双通道

**What to build:** REPL 旁路：/ask-for-help 切独立 thread（问答历史自累积、断点协议同构），直读磁盘项目文档切片（非主线对话历史）作答，天然最新无 staleness；仅项目工作流内可用。图内新手指引：guidance_mode=auto 每轮 / ask 先询问；入口做版本差检查（notes_version vs guidance_read_version，差>0 才注入）；指引以当轮材料包（round_summary + 最新 NOTE + 文档切片）单发生成，无历史累积；指引文本呈现于用户侧栏，绝不写入任何主线角色私有 key——隔离红线在指引通道同样生效。指引内容含"为什么这么做 + 下一步 + 技术栈文档链接"（链接经抓取验证有效）。

**Blocked by:** 06, 08, 09

**Status:** ready-for-agent

- [ ] 旁路：独立 thread 历史自累积、读项目文档切片作答（非主线历史）、追问上下文保持
- [ ] 工作流外 /ask-for-help 不可用
- [ ] 图内指引：仅版本差>0 注入、材料包单发无历史累积、指引文本不进任何主线私有 key
- [ ] guidance_read_version 读毕对齐（对齐后同材料不再重复注入）
- [ ] AskAgent 工具面 = 矩阵只读集（结构性断言无写权工具）
- [ ] 指引含为什么 + 下一步 + 文档链接；链接经抓取验证有效（假 fetch 预置死链被拒）
