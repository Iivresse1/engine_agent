# 11: demo 决议与 DemoAgent（生成不运行 + 报错回传环）

**What to build:** is_docs_finished=true → docs_done 断点（交付概览 + "构建 demo / 自定义答案"）→ demo_phase 三态路由（undecided / building / skipped，skipped 直通终检）。DemoAgent 全工具但运行类命令（执行 demo 本身）在权限层拒绝（ADR-0003）：生成 demo + 运行指南到工作区，用户亲手运行。报错回传：REPL 混合路由三层——显式斜杠优先（零 LLM）→ 报错特征规则预筛（Traceback / Error: 特征 + demo 阶段活跃）→ LLM 窄分类兜底（只判"报错回传 vs 普通输入"，默认去活跃 agent/Builder）；报错文本融合进 demo_messages 进修复循环，demo 环计数 Max_loop=5 封顶出 loop_exhausted。demo 轮同为 LLM 调用点，过统一压缩检查（08 联动）。

**Blocked by:** 06, 08

**Status:** done（2026-10-25 实现，合并 baa66ea）

- [x] docs_done 断点 → 自由文本决议 demo_phase（含跳过 / 自定义）
- [x] demo 生成到工作区 + 运行指南；运行类命令被权限层拒绝（测试注入验证）
- [x] 贴 Traceback 无命令直接路由进 DemoAgent（特征预筛）；普通文本默认去活跃 agent；斜杠优先级最高（三层序测试）
- [x] LLM 窄分类兜底只做二分（假模型二分脚本验证）
- [x] 报错融合进 demo_messages；修复循环 demo 环计数到 5 → loop_exhausted 断点
- [x] demo 轮过统一压缩检查（与 08 的挂点联动测试）

## Comments

**2026-10-25 实现 完成（implementer 子代理 4 提交 + Lead 收尾融合，合并 baa66ea，733 绿）**：hybrid_router.py 三层纯函数（斜杠/特征预筛需 demo 活跃/窄分类二分默认 normal）；docs_done_node 三态决议+入口行 7 改道 DOCS_DONE+demo 行；make_demo_agent_node（write_any 无白名单仅拦".."、运行权 ADR-0003 提示+"运行：{cmd}"零 ShellTool 调用、报错修复读 demo_messages）；REPL 三层接线（error_return 融合+demo_loop_count++）；with_compression 加 messages_key 参数（demo 挂点传 demo_messages，向后兼容）；Role.+DEMO_AGENT。**执行注记**：本票经历两轮子代理死亡——第二轮死于切片 3 后（测试全绿但未提交），Lead 提交其遗留+融合 10 票改动（/ask-for-help 五命令表+指引块）；第一轮的 bfc7a8d 残留提交经第二轮核验无重复逻辑。routing.py 行 7 现指 DOCS_DONE——12 票终检接管终态时改。
