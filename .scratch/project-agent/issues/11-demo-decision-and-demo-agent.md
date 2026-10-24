# 11: demo 决议与 DemoAgent（生成不运行 + 报错回传环）

**What to build:** is_docs_finished=true → docs_done 断点（交付概览 + "构建 demo / 自定义答案"）→ demo_phase 三态路由（undecided / building / skipped，skipped 直通终检）。DemoAgent 全工具但运行类命令（执行 demo 本身）在权限层拒绝（ADR-0003）：生成 demo + 运行指南到工作区，用户亲手运行。报错回传：REPL 混合路由三层——显式斜杠优先（零 LLM）→ 报错特征规则预筛（Traceback / Error: 特征 + demo 阶段活跃）→ LLM 窄分类兜底（只判"报错回传 vs 普通输入"，默认去活跃 agent/Builder）；报错文本融合进 demo_messages 进修复循环，demo 环计数 Max_loop=5 封顶出 loop_exhausted。demo 轮同为 LLM 调用点，过统一压缩检查（08 联动）。

**Blocked by:** 06, 08

**Status:** ready-for-agent

- [ ] docs_done 断点 → 自由文本决议 demo_phase（含跳过 / 自定义）
- [ ] demo 生成到工作区 + 运行指南；运行类命令被权限层拒绝（测试注入验证）
- [ ] 贴 Traceback 无命令直接路由进 DemoAgent（特征预筛）；普通文本默认去活跃 agent；斜杠优先级最高（三层序测试）
- [ ] LLM 窄分类兜底只做二分（假模型二分脚本验证）
- [ ] 报错融合进 demo_messages；修复循环 demo 环计数到 5 → loop_exhausted 断点
- [ ] demo 轮过统一压缩检查（与 08 的挂点联动测试）
