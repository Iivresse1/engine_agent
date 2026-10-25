# 磁盘文档为共享介质

项目文档直接以磁盘文件为跨角色共享的事实来源（git 可 diff、用户手改立即可见、文档即交付物本身），LangGraph Store 只承担 final_report 长期记忆与薄状态，不做文档主存储。官方 Store 没有 SQLite 实现是现实原因之一——InMemory 重启即丢、Postgres 对本地 CLI 过重；磁盘方案还让【R#】切片检索退化为纯文本处理。
