# 06: 【R#】轮次标记与共享文档区

**What to build:** actor 交付物落盘带【R#】轮次标记；ReadProjectDocs / NotepadRead 按轮次前缀切片检索；工作区 NOTES.md 为全角色共享外部记忆（条目带【R#】，NotepadAdd / NotepadRead 全员可用）；notes_version 在 NotepadAdd 成功后单调自增，guidance_read_version 在消费后对齐，版本差>0 才注入——stale-read 被结构性杜绝。磁盘为共享事实来源（ADR-0004）：角色间信息交换只经共享文档区，Store 不参与本轮。

**Blocked by:** 03, 05

**Status:** done（2026-10-25 实现，合并 2620011）

- [x] 每轮生成物带正确【R#】；按轮次切片检索只返回该轮切片
- [x] NotepadAdd 成功后 notes_version 单调自增；NOTES.md 落盘且条目带【R#】
- [x] 版本差检查：入口仅差>0 时注入；stale-read 杜绝测试绿（含"写 NOTE→摘要→AskAgent 读→对齐"序）
- [x] 隔离红线测试：角色 A 历史绝不出现于角色 B 输入，跨角色只经共享文档区

## Comments

**2026-10-25 实现 完成（implementer 子代理，5+1 提交，合并 2620011，467 绿，+46）**：src/project_agent/shared_docs.py（SharedDocs：BUILD_LOG.md【R#】轮次生成物多行条目/NOTES.md 单行条目/按轮切片；guidance_gate/align_guidance_read 版本门纯函数）；actor 扩展（round_count 仪表盘新字段/【R#】落盘/"记录："指令桥——07 票真身体接管前的最小通路/notes_version 按写入条数自增）；graph.build_graph(+workspace_root)。**隔离红线含变异验证**（临时泄漏 demo 历史入 BUILD_LOG→测试红→还原绿）。spec 已补录 v1.3（+round_count）。**边界钉定**："记录："单层 split（note 内再含分隔符拆多条）；read_round 同轮多条取首。cli/tools/.scratch 零改动核验。
