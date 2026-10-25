# 04: 本地 token 账单

**What to build:** usage_metadata 按 thread × 角色聚合（输入/输出/总数）落本地账单，用数据证明"隔离省 token"的核心主张；shell 审批的 deny/ask 落审计日志（规则 id + 命令段 + 原因码）。全部本地持久化，无任何云端观测路径（LangSmith 明确不引入）。

**Blocked by:** 01

**Status:** done（2026-10-25 实现，合并 c56c57d）

- [x] 假模型上报假 usage_metadata，账单按角色分账数字正确
- [x] 账单纯本地持久化，会话重启后可查
- [x] 审计日志含规则 id + 命令段 + 原因码
- [x] 代码中无网络上报路径（结构性断言）

## Comments

**2026-10-25 实现 完成（implementer 子代理，8 提交，75 绿，合并零冲突）**：src/project_agent/ledger.py（TokenLedger：thread×角色聚合 + JSON 持久化 + MeteredModel 包装层——ModelClient 协议形状不变，ScriptedModel 可作内层）、src/project_agent/audit.py（AuditEvent + AuditLog：JSONL 追加 + 按 thread/时间窗查询）。4 处关键守卫逐个变异验证（usage=None 宁漏不谎账 / 审计载入 / 时间窗过滤 / 网络库 import 禁令 AST 断言）。**接线待办**：MeteredModel 挂入 cli.py 装配（02 票引入首个图内 ModelClient 调用时做，账单路径建议 --state 同目录）；AuditLog 与 03 票权限 checker 的 deny/ask 事件接线（03 合并后做）。
