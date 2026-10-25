# LangGraph（Python）事实核查 — 2026-10

> 目的：为"主构建 agent + 教学子 agent"应用（共享项目文档、独立对话/思考上下文、按 agent 计量 token）核查 LangGraph 原生能力。
> 事实基准：官方文档 docs.langchain.com（LangGraph 1.x 时代；旧域名 langchain-ai.github.io/langgraph 已并入）。

## 1. Store API（BaseStore / InMemoryStore / PostgresStore）

**结论**：是。Store 是官方的跨线程（cross-thread）持久 KV 存储，与按 thread 隔离的 checkpointer 互补。数据按 namespace 元组组织，`put / get / delete / search / list_namespaces`（及 async `aput / aget / adelete / asearch / alist_namespaces`），`search` 支持 prefix 匹配与可选语义检索。完全适合当"两个 agent 共享的项目文档存储"——文档明确定位为 "long-term, cross-thread memory ... shared knowledge"，两个不同 `thread_id` 的运行用同一 store + 同一 namespace 即可共享数据。

**关键 API**：
- `store.put(namespace_tuple, key, value_dict, index=None)`；`store.get(namespace, key)`；`store.search(namespace_prefix, *, query=None, filter=None, limit=10, offset=0)`
- BaseStore 契约：5 个 async 方法必选，sync 版本建议实现
- 图内访问（1.x 新写法）：节点签名 `def node(state, runtime: Runtime[Context])`，用 `runtime.store` / `await runtime.store.aput(...)`；`compile(checkpointer=..., store=store)`
- 实现：`InMemoryStore`（开发）、`PostgresStore` / `AsyncPostgresStore`（生产）、MongoDB/Redis/Upstash 等

**版本敏感/易变警告**：
- 1.x 用 `Runtime` 对象注入 store；0.x 旧写法是 `config` 注入 / `langgraph.config.get_store()`——两代写法不同，教程混杂。
- 跨后端排序不一致（Postgres 按 `updated_at` 倒序、InMemory 按插入序），排序要客户端自己做。
- `search` 的 namespace 是**前缀匹配**不是精确匹配；超过 `limit` 静默截断。
- Agent Server（部署形态）自动提供 store；语义检索需在 `langgraph.json` 配 `store.index`。

来源：
- https://docs.langchain.com/oss/python/langgraph/stores
- https://docs.langchain.com/oss/python/langgraph/persistence

## 2. Checkpointer（BaseCheckpointSaver，SQLite/Postgres）

**结论**：是，对话历史严格按 `thread_id` 隔离。官方原文："The checkpointer uses `thread_id` as the primary key for storing and retrieving checkpoints"。每个 thread 是独立的状态/消息历史，两个不同 `thread_id` 的 graph 运行天然互不可见对方消息（除非你显式写入共享 Store）。新 `thread_id` = 全新空状态。

**关键 API**：
- `{"configurable": {"thread_id": "..."}}`（带 checkpointer 时必填）
- `graph.get_state(config)` / `get_state_history(config)` / `update_state(...)`
- `BaseCheckpointSaver`: `put / put_writes / get_tuple / list / delete_thread`（+ `a*` 异步版）
- 库：`langgraph-checkpoint`（InMemorySaver）、`langgraph-checkpoint-sqlite`（SqliteSaver/AsyncSqliteSaver）、`langgraph-checkpoint-postgres`（PostgresSaver/AsyncPostgresSaver）、MongoDB、CosmosDB
- 子图 checkpoint 有独立 `checkpoint_ns`（父图 `""`，子图 `"node_name:uuid"`，嵌套用 `|` 连接）

**版本敏感/易变警告**：
- PostgresSaver 的 `thread_id` 列长有限（保持 <255 字符）。
- InMemorySaver 重启即丢；生产用 Sqlite/Postgres。
- durability 三模式 `exit / async / sync`；`DeltaChannel`（beta，langgraph>=1.2）可减 checkpoint 体积但 API 易变。
- 同 thread 的子图状态变化父图不会立即可见（跨图边界共享要走 Store）。

来源：
- https://docs.langchain.com/oss/python/langgraph/checkpointers
- https://docs.langchain.com/oss/python/langgraph/persistence

## 3. 多 agent / 子 agent 隔离模式

**结论（2026 现状）**：
- **langgraph-supervisor 库已停止维护**（"no longer actively maintained"），官方迁移指引：改为 subagents 模式（主 agent 把子 agent 包成 `@tool`）。
- **subagents（agents-as-tools，官方推荐的 supervisor 替代）**：子 agent 默认 stateless、每次调用干净上下文（"context isolation"）。子 agent 的中间推理**是否**进入父 state 完全由你的 tool wrapper 决定——典型实现只返回 `result["messages"][-1].content`（最后一条消息），因此中间推理天然不进父消息历史。子 agent 内的 `interrupt()` 会冒泡到最外层图并可 `Command(resume=...)` 恢复。
- **subgraph 作为节点**：共享 state key（如 messages）时隔离弱；用 "call a subgraph inside a node"（父子不同 state schema + wrapper 转换）可为每个 agent 保留私有消息历史（文档原话："common when you want to keep a private message history for each agent"）。`compile(checkpointer=None|True|False)` = per-invocation（默认）/ per-thread / stateless 三种持久化。
- **Command handoff**：`Command(goto=..., update=..., graph=Command.PARENT)`；文档要求做显式 context engineering——建议只传 handoff pair（AIMessage + ToolMessage）而非全部历史，避免内部推理污染接收方上下文。
- **独立 thread_id 运行另一个 assistant**：最彻底的上下文隔离（见第 2 点），配合 Store 共享文档；Agent Server 可注册多个 assistant（`langgraph.json` 的 `graphs` 映射）。

**关键 API**：`create_agent` + `@tool` 包装 `subagent.invoke(...)`；`Command(goto, update, graph=Command.PARENT)`；子图 `compile(checkpointer=True/False/None)`；`graph.get_state(config, subgraphs=True)`。

**版本敏感/易变警告**：
- per-thread 子图不支持并行工具调用（checkpoint namespace 冲突）；需唯一节点名 wrapper 做 namespace 隔离。
- 在 tool 函数里调用的子 agent 无法被静态发现，`get_state(subgraphs=True)` 拿不到其状态（要可观测就从节点函数调）。
- `create_supervisor` / `create_handoff_tool` / `create_react_agent` 均为旧 API（→ `create_agent`）。

来源：
- https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs
- https://docs.langchain.com/oss/python/langgraph/use-subgraphs
- https://docs.langchain.com/oss/python/migrate/langgraph-supervisor
- https://docs.langchain.com/oss/python/langchain/multi-agent

## 4. LangGraph Server / Studio / Platform（`langgraph dev`）

**结论**：是。`langgraph dev` 启动本地 in-memory Agent Server（`http://127.0.0.1:2024`）并给出 **LangSmith Studio** UI（`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`）。Studio 有 graph 模式和 **chat 模式**（轻量聊天界面：流式回复、tool call 展示/隐藏）。可在 `langgraph.json` 的 `graphs` 里注册多个 graph（每个 graph ID 即一个 assistant，例如 `{"agent": ..., "storm": ...}`；也可在同一 graph 上建多个 assistant 配置），**chat 模式顶部下拉切换 assistant**；右侧面板查看/切换/新建 threads（`+ New Thread`）、fork、编辑历史。

**关键 API/命令**：`pip install "langgraph-cli[inmem]"` → `langgraph dev`（--tunnel 供 Safari）；SDK `client.runs.stream(thread_id_or_None, "assistant_name", input=..., stream_mode=...)`；REST `POST /runs/stream`（assistant_id）。

**版本敏感/易变警告**：
- **品牌/命名大改**：LangGraph Server/Platform → 现称 **Agent Server** + **LangSmith Deployments**（`langgraph dev` / `up` / `build` / `deploy`）。
- `langgraph dev` 是 in-memory 开发模式，重启丢数据；生产要 LangSmith Deployment（checkpointer 默认 Postgres、BaseStore 自动配置，无需手动）。
- Studio 免费但需 LangSmith 账号/API key；`LANGSMITH_TRACING=false` 可不上报。
- 另有开源 **Agent Chat UI**（agentchat.vercel.app / github.com/langchain-ai/agent-chat-ui）可连本地或部署的 Agent Server，渲染 tool call/interrupt。

来源：
- https://docs.langchain.com/oss/python/langgraph/local-server
- https://docs.langchain.com/oss/python/langgraph/studio
- https://docs.langchain.com/langsmith/use-studio（chat 模式切换 assistant / threads）
- https://docs.langchain.com/oss/python/langgraph/ui（Agent Chat UI）
- https://docs.langchain.com/langsmith/cli（langgraph.json 多 graphs、命令表）

## 5. Token 用量计量

**结论**：计量数据原生齐全，但**没有开箱即用的"按 agent 账单"**，聚合逻辑要自己写（或用 LangSmith 观测）。数据源四层：
1. **`AIMessage.usage_metadata`**（标准化 `UsageMetadata`：`input_tokens / output_tokens / total_tokens` + `input_token_details`（cache_read 等）/ `output_token_details`（reasoning 等））——挂在每条 AI 消息上，持久化在 checkpoint 里，事后可从 state 聚合。
2. **`stream_mode="updates"`**：每个 chunk 是 `{node_name: update}`，model 节点 update 里的 AIMessage 自带 `usage_metadata` → **天然可按节点聚合**。`stream_mode="messages"` 的 metadata 含 `langgraph_node`（节点名）、`tags`、`lc_agent_name`（`create_agent(name=...)` 时）→ **可按 agent 归属 token**；`subgraphs=True` 能流出子 agent 的 token。
3. **event streaming（推荐新 API，LangGraph v1.2+）**：`graph.stream_events(input, version="v3")`，`stream.messages` 的每条 message 有 `message.output.usage_metadata`；`message-finish` 事件含 token usage；`stream.subgraphs` 按 `graph_name` 区分嵌套 agent。官方文档直接给了 **`StatsTransformer` 示例**：实现 `StreamTransformer`（`required_stream_modes=("messages",)`，`process()` 里累加 `usage.get("output_tokens")`，`finalize()` 推送总计）——这就是官方的 token 聚合扩展点，可按 namespace/subgraph 再分组即得"按 agent 计量"。可 `compile(transformers=[...])` 或调用时传入。
4. **LangSmith**：trace 里每节点/每次 LLM 调用有 token/latency 指标（Studio 可看），适合观测与事后分析。

**版本敏感/易变警告**：
- stream v2 格式需 LangGraph>=1.1；event streaming v3 需 v1.2+；旧 `astream_events`（langchain_core 事件 API）仍可用但文档主推 `stream_events(version="v3")`。
- `usage_metadata` 由 chat model 集成填充；非 LangChain 集成的模型要走 `custom` 流自报。
- reasoning tokens 计入 `output_token_details.reasoning`，不同 provider 字段有差异。

来源：
- https://docs.langchain.com/oss/python/langgraph/streaming（含 usage_metadata 实输出示例、langgraph_node/lc_agent_name 过滤）
- https://docs.langchain.com/oss/python/langgraph/event-streaming（StatsTransformer 聚合示例）
- https://docs.langchain.com/oss/python/langchain/streaming
- https://reference.langchain.com/python/langchain-core/messages/ai/UsageMetadata

## 6. Human-in-the-loop（interrupt / Command(resume)）

**结论**：当前 API 形态：节点/工具内任意位置调 `interrupt(payload)`（payload 需 JSON 可序列化），图暂停并**用 checkpointer 持久保存状态，无限期等待**（"Graph waits indefinitely"）；用**同一 thread_id** 再 `invoke / stream / stream_events` 一个 `Command(resume=value)` 恢复，resume 值成为 `interrupt()` 调用的返回值。等待期间状态持久（生产配 Sqlite/Postgres checkpointer 可跨进程、跨重启等待人工输入）。

**关键 API**：
- `from langgraph.types import interrupt, Command`
- `interrupt(value, response_schema=Decision)`（`langgraph>=1.2.12`，Pydantic/TypedDict/dataclass 校验 resume 值）
- 结果位置：`result["__interrupt__"]`（invoke）；`stream.interrupts` / `stream.interrupted`（`stream_events(version="v3")`）
- 并行多中断：`Command(resume={interrupt_id: value})` 映射
- 静态断点 `interrupt_before / interrupt_after` 仅供调试，不推荐用于 HITL

**规则/警告**：恢复时**整个节点从头重跑**（interrupt 前的代码会重复执行，副作用需幂等）；不要用 try/except 包 interrupt；同节点多个 interrupt 按索引严格匹配、顺序必须确定；`while True` + interrupt 校验循环会导致指数重放（应改用 conditional edge）。

来源：
- https://docs.langchain.com/oss/python/langgraph/interrupts

## 总体结论（针对"共享文档、隔离思考、分角色计量 token"）

**原生覆盖**：① 共享文档——Store（跨线程 namespace KV + 语义检索）就是为此设计的；② 隔离思考——`thread_id` 天然隔离对话历史（每个 agent 一条 thread 互不可见），subagents-as-tools 模式下子 agent 每次调用干净上下文、中间推理默认只以 tool wrapper 返回的最后消息回到父图，`checkpointer=True` 还能让子 agent 拥有自己的跨调用私有记忆；③ HITL——`interrupt()` + `Command(resume=...)`，等待期状态持久；④ UI——`langgraph dev` + Studio chat 模式（多 assistant 下拉切换、多 thread 管理），或开源 Agent Chat UI。

**缺口/需自建**：① **按 agent 的 token 记账没有现成聚合**——数据都在（usage_metadata / updates 流的 per-node 归属 / messages 流的 `lc_agent_name` / 事件 transformer / LangSmith），但"分角色计量"要自己写聚合（官方 StatsTransformer 是起点，需自行按 agent 名/namespace 分组持久化，或直接用 LangSmith 的按 run 统计）；② "思考隔离"不是绝对保证——subagent 返回什么进父上下文由你的 tool wrapper 决定，共享 state key 的 subgraph 会把子图消息写进父 messages；③ per-thread 子 agent 有并行调用冲突和 namespace 隔离坑；④ langgraph-supervisor 已停维护，supervisor 拓扑要自己用 `create_agent` + `@tool` 组装。版本上注意 0.x→1.x 的 API 代际差（Runtime 注入、stream_events v3、create_agent）。
