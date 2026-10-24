# 09: 上下文工程·两段式送达 + 作用域 + 技能懒加载

**What to build:** Context Assembler 两段式的完整形态。装：图内节点每轮组装 assembled_context（base prompt + 作用域规则 + todo 板 + notepad 切片 + 技能头 + 工具子集声明）并整覆写。送：actor 中间件三件套送达——@dynamic_prompt 组 system / wrap_model_call 以 tools 子集 override / before_agent 版本号检查。作用域：规则文件（按工作区域分文件）+ current_scope state 字段落定；工具子集 = 规则声明集 ∩ 静态权限矩阵。技能懒加载：上下文只注技能名 + 一句话描述，SKILL.md 触发时才全文读入；推荐理由 ≤20 字代码硬约束。

**Blocked by:** 05, 06

**Status:** ready-for-agent

- [ ] 每轮 assembled_context 整覆写、内容按 current_scope 组装
- [ ] 假模型断言：实际收到的 system 为动态组装、tools 为作用域裁剪后子集
- [ ] 工具子集严格 = 规则声明集 ∩ 静态矩阵（越界测试：规则声明的工具不在矩阵内不生效）
- [ ] 技能只注名字 + 一句话；触发才读全文
- [ ] 推荐理由超 20 字被代码层拒绝
- [ ] before_agent 版本号检查挂通（notepad 切片按 notes_version 取新）
