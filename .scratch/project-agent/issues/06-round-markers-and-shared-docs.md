# 06: 【R#】轮次标记与共享文档区

**What to build:** actor 交付物落盘带【R#】轮次标记；ReadProjectDocs / NotepadRead 按轮次前缀切片检索；工作区 NOTES.md 为全角色共享外部记忆（条目带【R#】，NotepadAdd / NotepadRead 全员可用）；notes_version 在 NotepadAdd 成功后单调自增，guidance_read_version 在消费后对齐，版本差>0 才注入——stale-read 被结构性杜绝。磁盘为共享事实来源（ADR-0004）：角色间信息交换只经共享文档区，Store 不参与本轮。

**Blocked by:** 03, 05

**Status:** ready-for-agent

- [ ] 每轮生成物带正确【R#】；按轮次切片检索只返回该轮切片
- [ ] NotepadAdd 成功后 notes_version 单调自增；NOTES.md 落盘且条目带【R#】
- [ ] 版本差检查：入口仅差>0 时注入；stale-read 杜绝测试绿（含"写 NOTE→摘要→AskAgent 读→对齐"序）
- [ ] 隔离红线测试：角色 A 历史绝不出现于角色 B 输入，跨角色只经共享文档区
