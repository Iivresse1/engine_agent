# 04: 本地 token 账单

**What to build:** usage_metadata 按 thread × 角色聚合（输入/输出/总数）落本地账单，用数据证明"隔离省 token"的核心主张；shell 审批的 deny/ask 落审计日志（规则 id + 命令段 + 原因码）。全部本地持久化，无任何云端观测路径（LangSmith 明确不引入）。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 假模型上报假 usage_metadata，账单按角色分账数字正确
- [ ] 账单纯本地持久化，会话重启后可查
- [ ] 审计日志含规则 id + 命令段 + 原因码
- [ ] 代码中无网络上报路径（结构性断言）
