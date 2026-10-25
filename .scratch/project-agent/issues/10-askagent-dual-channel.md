# 10: AskAgent 双通道

**What to build:** REPL 旁路：/ask-for-help 切独立 thread（问答历史自累积、断点协议同构），直读磁盘项目文档切片（非主线对话历史）作答，天然最新无 staleness；仅项目工作流内可用。图内新手指引：guidance_mode=auto 每轮 / ask 先询问；入口做版本差检查（notes_version vs guidance_read_version，差>0 才注入）；指引以当轮材料包（round_summary + 最新 NOTE + 文档切片）单发生成，无历史累积；指引文本呈现于用户侧栏，绝不写入任何主线角色私有 key——隔离红线在指引通道同样生效。指引内容含"为什么这么做 + 下一步 + 技术栈文档链接"（链接经抓取验证有效）。

**Blocked by:** 06, 08, 09

**Status:** done（2026-10-25 实现，合并 baa66ea）

- [x] 旁路：独立 thread 历史自累积、读项目文档切片作答（非主线历史）、追问上下文保持
- [x] 工作流外 /ask-for-help 不可用
- [x] 图内指引：仅版本差>0 注入、材料包单发无历史累积、指引文本不进任何主线私有 key
- [x] guidance_read_version 读毕对齐（对齐后同材料不再重复注入）
- [x] AskAgent 工具面 = 矩阵只读集（结构性断言无写权工具）
- [x] 指引含为什么 + 下一步 + 文档链接；链接经抓取验证有效（假 fetch 预置死链被拒）

## Comments

**2026-10-25 实现 完成（implementer 子代理 5 提交 + Lead 融合入 11 票分支，合并 baa66ea，733 绿含 11 票）**：ask_agent.py（ASK_TOOLSET 10 件只读集/build_ask_context 磁盘切片/ask_answer 独立历史/AskBypass/guidance_material_pack/build_guidance 单发/verify_link）；REPL /ask-for-help（工作流守卫三态/图外作答零 state 写）；actor 后置指引工序（版本门+材料包+round_output 尾部注入+读毕对齐）。**已知语义注记（实现者异议）**：09 的 assembler 与 10 的指引共用 guidance_read_version 门——入轮前已有版本差会被 assembler 先消费对齐，图级指引只在 actor 本轮自增 NOTE 时注入；按终裁字面实现未改 09，若需"入轮即有差必须由指引通道注入"需另行裁定门归属。verify_link 为纯边界函数（真实 WebFetch 接线留 CLI/接线票）。
