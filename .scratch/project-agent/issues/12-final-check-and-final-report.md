# 12: 终检管线与 final_report

**What to build:** finalizer 收尾整理产 final_report → Store 跨线程长期记忆（新会话 ask_tasks 时可检索注入）。check_proper_output 终检管线：LLM 检测标记（含畸形变体）→ 快照备份 → 正则剥离【R#】→ 确定性 diff 校验（变更行只含标记，否则判误伤）→ LLM 语义校验（删除前后内容一致）→ 双份交付（备份版 + 干净版）；output_clean 置位 → FINISH（finished 断点 payload 含双份交付路径，终态旁路问答仍可用）。不过 → 回 planner 开新完整循环（系统性修复非单轮补丁），终检环计数 ≤5，耗尽出 loop_exhausted 交人工。交付物对账：按所选构建方式的文档集定义核对完整性。

**Blocked by:** 07, 08, 11

**Status:** ready-for-agent

- [ ] 全 lifespan 回放（ask_tasks → … → FINISH）：双份交付、零【R#】残留
- [ ] 畸形标记变体被 LLM 检测层抓到（预置变体注入测试）
- [ ] 确定性 diff：变更行只含标记；混入内容变更 → 判误伤不过
- [ ] 语义校验失败 → 回 planner 开新环（非补丁）；终检环计数=5 → loop_exhausted
- [ ] final_report 入 Store；模拟新会话跨 thread 检索读回
- [ ] 交付物完整覆盖所选方式文档集（对账表驱动）；skipped demo 直通终检
