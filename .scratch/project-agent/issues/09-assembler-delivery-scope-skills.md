# 09: 上下文工程·两段式送达 + 作用域 + 技能懒加载

**What to build:** Context Assembler 两段式的完整形态。装：图内节点每轮组装 assembled_context（base prompt + 作用域规则 + todo 板 + notepad 切片 + 技能头 + 工具子集声明）并整覆写。送：actor 中间件三件套送达——@dynamic_prompt 组 system / wrap_model_call 以 tools 子集 override / before_agent 版本号检查。作用域：规则文件（按工作区域分文件）+ current_scope state 字段落定；工具子集 = 规则声明集 ∩ 静态权限矩阵。技能懒加载：上下文只注技能名 + 一句话描述，SKILL.md 触发时才全文读入；推荐理由 ≤20 字代码硬约束。

**Blocked by:** 05, 06

**Status:** done（2026-10-25 实现，合并 7890bd1）

- [x] 每轮 assembled_context 整覆写、内容按 current_scope 组装
- [x] 假模型断言：实际收到的 system 为动态组装、tools 为作用域裁剪后子集
- [x] 工具子集严格 = 规则声明集 ∩ 静态矩阵（越界测试：规则声明的工具不在矩阵内不生效）
- [x] 技能只注名字 + 一句话；触发才读全文
- [x] 推荐理由超 20 字被代码层拒绝
- [x] before_agent 版本号检查挂通（notepad 切片按 notes_version 取新）

## Comments

**2026-10-25 实现 完成（implementer 子代理，6 提交，合并 7890bd1，594 绿，+29）**：scopes.py（RULES 三区+ALLOWED_TOOLS_BY_SCOPE+交集语义）；skills.py（SkillHead 三头/skill_body 触发全文/recommendation_reason ≤20 截断）；make_assembler_node 工厂（五段 system：base+作用域+todo 板+Notepad 版本门控块+技能头；新键 tools_subset/skills；guidance_read_version 节点写对齐——stale-read 杜绝）；actor 送达（system 尾行【可用工具】清单+技能触发桩+理由截断桩）。**关键终裁**：工具子集送达不用 langchain middleware（版本敏感 API 风险），改 assembler 装入 system + actor 尾行送达——语义等价零版本风险。**合并注记**：与 07 并行改 nodes.py，合并解三处冲突（7890bd1）——assembler 取本票工厂骨架织入 07 脚手架提示、助手函数两组全留、actor 尾部组合（_delivery_output 先行+白名单拒绝提示）。
