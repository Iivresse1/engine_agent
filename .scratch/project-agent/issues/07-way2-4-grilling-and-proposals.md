# 07: way2–4 grilling 形态与三方案并行

**What to build:** 三档构建方式真身：轻 grill（IDEA.md 一页纸 + 短 grilling 直达 demo 语境）/ 简化文档（README + TODO + 目录树）/ 完整文档（DocScaffold 框架先行、grilling 指引逐步填写——文档长出来而非倒出来），全部由问题断点驱动文档生长。way4 专属：grilling 到位后三方案并行（proposal_set ≤3 套方案摘要，技术栈 × 复杂度取舍维度）→ choice:proposal 断点 → 用户自由文本选定或融合 → selected_proposal 写盘后才进 planner 深化。各方式文档集定义成表（交付物对账依据，终检票消费）。

**Blocked by:** 05, 06

**Status:** done（2026-10-25 实现，合并 31293df）

- [x] way2 / way3 / way4 各回放一条会话脚本：文档集按方式生成且带【R#】
- [x] 完整文档方式：框架先行、内容随 grilling 逐轮生长（非一次倾倒）
- [x] way4：三方案并行产出、choice:proposal 断点、序号与融合文本均正确解释、选定后深化
- [x] 轻方式不生成 way3/4 文档集（文档集对账表驱动）
- [x] planner 按 selected_proposal（或方式默认）产 todos

## Comments

**2026-10-25 实现 完成（implementer 子代理，6 提交，合并 31293df，564 绿，+97）**：deliverables.py（DELIVERABLE_SETS way1-4 定义表——12 票终检对账对象）；_grilling_body（way2-4 身体：澄清行 prompt）；"写入："行首解析+SharedDocs.write_deliverable 白名单；way4 DocScaffold（assembler 追加行+首轮占位框架幂等+逐轮生长断言）；make_proposals_node（三案解析/choice:proposal 断点/序号+关键词决议/复用重发零调用/兜底三案）+入口路由新行（PROPOSALS 判定插 todos 前）；planner 深化首项（40 字截断）。**合并注记**：与 09 并行改 nodes.py，合并时 assembler 以 09 工厂形态为骨架、07 脚手架提示织入工厂内层；way4_scaffold 测试适配工厂形态（7890bd1）。"记录："桥子串命中 vs "写入："行首命中的语义差异有测试钉定。
