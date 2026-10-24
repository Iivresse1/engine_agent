# 01: REPL 壳与主图骨架（断点协议跑通）

**What to build:** 应用级首启（首次启动问一次模型/API 配置并写盘，之后零提问直达会话）→ REPL 主循环（斜杠命令前缀识别零 LLM 分发；非斜杠输入默认进主工作流图）→ 挂 checkpointer 的最小主图。一轮 = 一次完整图执行；END 即断点：turn_end_reason 与 turn_end_payload 落盘、控制权交还 REPL；下一条自由 prompt 同 thread 融合续跑。入口路由器（START 后纯代码条件边组）实现真值表前 3 行（task_brief 未设→ask_tasks / build_way 未设→build_ways / default 占位）。同时建立测试基建：src 布局、独立测试树、测试依赖走 extras 分组、零反向 import、测试替身（可编程假模型/假 shell/tmp 工作区回放脚手架）不随主包分发。契约依据：spec『状态契约』节的断点协议表与仪表盘字段表。

**Blocked by:** None（can start immediately）

**Status:** ready-for-agent

- [ ] 首启问一次模型/API 写盘，再启零提问直达会话
- [ ] 斜杠命令前缀匹配零 LLM 分发；非斜杠输入进主图
- [ ] 每轮 END 后 turn_end_reason + turn_end_payload 落盘可查，控制权回 REPL
- [ ] 下条自由文本同 thread 融合进目标私有 key，状态由 checkpointer 恢复
- [ ] 断点协议表 7 种 reason 的 state 形状定义齐全并被测试引用
- [ ] 入口路由真值表前 3 行表驱动测试通过（假模型，零真模型）
- [ ] 测试与主项目物理分隔五条全满足（独立测试树 / extras 依赖组 / 零反向 import / 替身不随主包分发 / 测试配置独立）
- [ ] 回放脚本"首启→两轮→断点续跑"全程绿
