# 05: Actor 工厂与主环（way1 形态）

**What to build:** 8 配置条件边（build_way × guidance_mode → Actor 工厂参数，每轮派生不持久化）；planner 读 task_brief 与方式产 todos（全 pending、工作流级清单）并清零主环计数；占位版 context_assembler 写 assembled_context；actor 跑 way1 ReAct 循环，轮终写私有历史追加 + todos 勾选 + turn_end_reason=round；verifier 由 LLM 判内容置位 task_complete / is_docs_finished；条件边纯代码读 gate AND todos_all_completed：todos 未清回 actor / 清而 gate 未过回 planner（主环计数++）/ 双过放行 / 计数=5 出 loop_exhausted 断点。actor 节点内置后置工序显式调用提炼函数产 round_summary（Q53=b：节点函数末尾、写 gate 前，纯函数可单测）。

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] gate AND todos 判定矩阵表驱动绿（未清回 actor / 清而未过回 planner / 双过放行）
- [ ] 主环计数=5 → loop_exhausted 断点，payload 含现场与求助说明
- [ ] round 断点为默认形态；下条输入融合进 actor_messages
- [ ] round_summary 由 actor 节点末尾显式工序产出，提炼函数独立单测绿
- [ ] 8 配置（4 方式 × 2 指引）派生表驱动绿
- [ ] todos_all_completed 为纯代码三态扫描
- [ ] 隔离红线：assembler / actor 的输入不含任何其他角色历史
