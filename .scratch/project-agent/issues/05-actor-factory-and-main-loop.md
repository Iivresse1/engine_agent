# 05: Actor 工厂与主环（way1 形态）

**What to build:** 8 配置条件边（build_way × guidance_mode → Actor 工厂参数，每轮派生不持久化）；planner 读 task_brief 与方式产 todos（全 pending、工作流级清单）并清零主环计数；占位版 context_assembler 写 assembled_context；actor 跑 way1 ReAct 循环，轮终写私有历史追加 + todos 勾选 + turn_end_reason=round；verifier 由 LLM 判内容置位 task_complete / is_docs_finished；条件边纯代码读 gate AND todos_all_completed：todos 未清回 actor / 清而 gate 未过回 planner（主环计数++）/ 双过放行 / 计数=5 出 loop_exhausted 断点。actor 节点内置后置工序显式调用提炼函数产 round_summary（Q53=b：节点函数末尾、写 gate 前，纯函数可单测）。

**Blocked by:** 01, 02

**Status:** done（2026-10-25 实现，合并 f689b88）

- [x] gate AND todos 判定矩阵表驱动绿（未清回 actor / 清而未过回 planner / 双过放行）——test_verifier.py GATE_MATRIX 8 行参数化；票面"未清回 actor"按 Q61 轮节律终裁实现为"未清→END（round 断点收轮，下轮入口路由回 assembler）"，拓扑语义等价
- [x] 主环计数=5 → loop_exhausted 断点，payload 含现场与求助说明——test_loop_exhausted.py（scene+help_text）+ 耗尽回放 + 耗尽恢复（planner 见 count>=5 清零开新循环）
- [x] round 断点为默认形态；下条输入融合进 actor_messages——大回放逐轮断言
- [x] round_summary 由 actor 节点末尾显式工序产出，提炼函数独立单测绿——distill_round 8 测 + Q53=b 显式调用
- [x] 8 配置（4 方式 × 2 指引）派生表驱动绿——derive_actor_config 19 测
- [x] todos_all_completed 为纯代码三态扫描——verifier 节点纯扫描（空表 False 防御）
- [x] 隔离红线：assembler / actor 的输入不含任何其他角色历史——单测+图级 DEMO_PRIVATE_MARKER 断言

## Comments

**2026-10-25 实现 完成（implementer 子代理第三次重启终裁版，8+1 提交，合并 f689b88，421 绿，+91 测试）**：planner（todos 模板/重规划计数保留/count>=5 清零开新循环）/ context_assembler（整覆写）/ actor 工厂（model=None 骨架不挂死）/ verifier（fail-closed 解析+计数自增节点写）/ _after_verifier gate 矩阵 / LOOP_EXHAUSTED 断点 / derive_actor_config 8 配置 / distill_round。**拓扑演进**：PLACEHOLDER 节点/常量全删（入口路由全覆盖）；图内唯一回边 = verifier→planner；Role 枚举 +VERIFIER（ModelClient.role 受控词汇，fusion 映射未动）。**耗尽态不对称设计（有意）**：图内边计数最前（耗尽即时触发）；入口边 todos 先序（耗尽恢复输入走 planner 清零——若计数先序会卡死恢复路径，Lead 异议核实后撤回）。02 测试占位断言→已列出（planner 轮）。cli.py 仅 TODO 注释（MeteredModel 接线待真模型票）。
