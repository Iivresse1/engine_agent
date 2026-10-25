# 12: 终检管线与 final_report

**What to build:** finalizer 收尾整理产 final_report → Store 跨线程长期记忆（新会话 ask_tasks 时可检索注入）。check_proper_output 终检管线：LLM 检测标记（含畸形变体）→ 快照备份 → 正则剥离【R#】→ 确定性 diff 校验（变更行只含标记，否则判误伤）→ LLM 语义校验（删除前后内容一致）→ 双份交付（备份版 + 干净版）；output_clean 置位 → FINISH（finished 断点 payload 含双份交付路径，终态旁路问答仍可用）。不过 → 回 planner 开新完整循环（系统性修复非单轮补丁），终检环计数 ≤5，耗尽出 loop_exhausted 交人工。交付物对账：按所选构建方式的文档集定义核对完整性。

**Blocked by:** 07, 08, 11

**Status:** done（2026-10-25 实现，合并 08bc4b7）

- [x] 全 lifespan 回放（ask_tasks → … → FINISH）：双份交付、零【R#】残留
- [x] 畸形标记变体被 LLM 检测层抓到（预置变体注入测试）
- [x] 确定性 diff：变更行只含标记；混入内容变更 → 判误伤不过
- [x] 语义校验失败 → 回 planner 开新环（非补丁）；终检环计数=5 → loop_exhausted
- [x] final_report 入 Store；模拟新会话跨 thread 检索读回
- [x] 交付物完整覆盖所选方式文档集（对账表驱动）；skipped demo 直通终检

## Comments

**2026-10-25 实现 完成（implementer 子代理 4+1 提交，合并 08bc4b7，791 绿，+58）**：final_check.py（MARKER_RE 三形态剥离/畸形区间扣除法/marker_only_diff 确定性 diff/snapshot files-only/llm_semantic_check fail-closed/run_final_check 对账管线）；memory_store.py（InMemoryStore，langgraph 正式 Store 留接线票）；make_finalizer_node（四要素 prompt→final_report 入 Store key=final_report:{brief}）+ make_check_node（FINISHED 断点/回 planner 新环/耗尽含明细）+ 图三入口接线 + build_graph(+store)。**拓扑终局改向**：DEMO_AGENT→FINALIZER（11 票原 END 边替换，9 处旧断言按终裁更新）；DOCS_DONE 出口 skipped/done→FINALIZER；入口行 8（skipped 直通终检）。**异议记录**：终检不过开新环后 planner 模板板覆盖修复 todo（只存一轮）——修复项持续性留后续票。**12 票闭=全部 12 张实现票完成**。
