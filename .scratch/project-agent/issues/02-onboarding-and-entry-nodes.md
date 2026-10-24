# 02: 首启两层与入口三节点

**What to build:** 项目级首启问卷（用户模式 / 新手指引三态 / 决策模式 / 技能包选择）并入 ask_tasks 流程，只在首次进工作流时出现。ask_tasks 产 task_brief（一次写定不再改写）；build_ways 出 choice:build_way 断点（4 种构建方式 + 推荐 + 一句话理由），用户自由文本（含序号或自然语言）由决议节点解释后写 build_way；guidance_trigger 纯配置映射写 guidance_mode 三态。AskUserQuestion 形态 = 提问断点（选项仅渲染辅助，答案自由文本融合）。

**Blocked by:** 01

**Status:** done

- [x] 项目级四问只出现在首次进工作流，之后直达（大回放后续轮零 question reason；seed 字段直达）
- [x] task_brief 写定后不被后续轮改写（恒定断言）
- [x] choice:build_way 断点 payload 含 4 选项 + 推荐 + 一句话理由；"1"、"用完整文档"等自由文本均正确解释
- [x] guidance_mode 三态（自动每轮/每轮询问/关）落盘（映射表 + 回放 + 跨实例持久化）
- [x] 入口路由真值表 task_brief / build_way 两行表驱动测试绿
- [x] 产生提问断点的节点可重入：提前返回后下轮重进不重复副作用（重问幂等 + choice 复用重发零 model 调用）
