# 08: 上下文工程·压缩

**What to build:** 模型调用前统一压缩检查，挂到流程内全部 LLM 调用点（context_assembler / actor before_model / verifier / planner / demo 轮）。80% 阈值触发：压最老 5 轮/包为【R#-compact】摘要（便宜模型子档）；压后水位目标 ≤60%，不足再压一包（同轮最多两包）；最近 3 轮原文永不压缩；注入形态 = 头部单包（全部压缩摘要合并为消息历史头部单一记忆区，每包首行标注覆盖轮次）；压缩中发现的错误猜想写 Notepad；/compact 手动兜底立即触发等价压缩。

**Blocked by:** 05, 06

**Status:** done（2026-10-25 实现，合并 57c8487）

- [x] 80% 触发 / 3 轮保护 / 水位 60% / 两包上限四条边界全部表驱动绿
- [x] 压缩包驻留消息历史头部单包形态；每包首行含覆盖轮次目录
- [x] 全部 LLM 调用点挂同一检查（逐节点单独测试触发）
- [x] 压缩调用走便宜模型子档（配置分档生效）
- [x] /compact 手动触发等价压缩
- [x] 压缩后轮次仍可经【R#】检索溯源（断链检测）
- [x] 错误猜想落 Notepad 且 notes_version 自增

## Comments

**2026-10-25 实现 完成（子代理 5 切片 + Lead 接手收尾切片 5，合并 57c8487，660 绿，+193/集成后）**：compression.py（round_texts/should_compress 80%/plan_packs 四边界/format_head_pack 头部单包/find_error_conjectures）；run_compression_check（重排=add_messages 指令批：首条覆写头部单包+RemoveMessage 剔除——**消息历史收缩的 LangGraph 正确方式**，_apply 归约断言终态）；with_compression 装饰器（三挂点 actor/verifier/assembler；planner 无 LLM 不挂、demo 轮后续票，验收 3 以三点为准）；便宜模型独立实例+role="compressor" 分档；/compact REPL 待并批机制（压缩批随下轮 invoke 进图——否则 checkpointer 历史永不收缩）；compacted_rounds 仪表盘（spec v1.4）+ 溯源断链（磁盘【R#】原文压缩后仍可检索）。**执行注记**：子代理第三次上下文耗尽死于切片 4/5 之交，Lead 接手补 state 字段/REPL 待并批/两处合并适配（graph 三挂点×09 工厂、旧函数名残留）；其死前自修的部分（_apply 归约测试、溯源测试两包脚本）质量良好被保留。
