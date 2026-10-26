# 16: UX-3 前端与传输 —— WebSocket 传输 + Ink 前端 + Bun 打包

**Status:** in_progress（片 1–3 已落地：传输层 + Ink 骨架 + 面板按键，906 后端测试 + 26 前端测试全绿；片 4–5 未完）
**类型:** UX 实现票（ADR-0005 双运行时）
**开票:** 2026-10-26
**依赖:** 15 票（协议消息表 + 翻译层已落）

**实现记（片 1 + 片 2）**：
- **片 1 传输层**：`transport.py` —— 握手文件（原子写/六字段校验/bool 冒充 int 拦/pid 存活判定/清理）+ `ProtocolServer`（坏 JSON 与不合协议回 notice 不崩）+ `make_serve`（延迟 import websockets）+ `_bound_port`。`repl.py` 抽出 `_emit`/`_notice`/`handle_input`，22 处直写改走消息出口；终端行为逐字不变。后台 906 测试（+24）。
- **片 2 Ink 骨架**：`frontend/`（TS + React 19 + Ink 8 + ws）——`protocol.ts`/`handshake.ts`/`client.ts`/`width.ts`/`App.tsx`/`main.tsx`；`tsc` 类型与构建零错；`vitest` 12 例（协议解析 6、握手 4、字宽 2）。前端只按 type 渲染、断点文案直用后端 `lines`。
- **真实联调**：后端起在随机端口 57297，前端读握手文件发现并连上，跑通 `input → round_end → choice:build_way → farewell`。
- **修掉一处前端校验漏洞**：`payload: []`（数组）曾被 `typeof === "object"` 漏过，与后端 `messages.py` 严格性不一致；已补 `Array.isArray` 拒绝，并造红转绿。
- **片 3 面板与按键**：常驻按键提示行 `Enter 提交 · Ctrl+O 状态面板 · Ctrl+T 教学页 · Esc 退出`；`Ctrl+O` 折叠状态面板（显示最近 `task_brief:` 状态行与最近断点）；`Ctrl+T` 折叠教学页面板（显示路径/轮次，不内联渲染 HTML）；教学页到达时自动展开。
- **可测性重构**：把纯展示部分抽成 `TranscriptView`（无 hooks/无副作用），用 ink `renderToString` 做真实渲染断言（6 例）；`toEntries` 导出为纯函数，面板取数直接测真实实现而非镜像副本。`subscribe` 改为 prop 注入（不再依赖全局单例），便于测试与替换。
- **工具事实**：Ink 8 无 `lastFrame`；`renderToString` 不跑 effect（需纯组件才可渲染断言）；Windows 下无 `pty`/`termios`（PTY 冒烟不可用）——这三点促使"纯视图 + renderToString"成为唯一可靠的渲染测试路径。

## 目标

把 `messages.py` 的消息表接到真实传输与真实观感上：后端起 WebSocket 服务，前端用 Ink 渲染并采集按键。

## 已由 spec 钉死的部分（不得再设计）

- **消息表与形状**：见 spec『协议消息层』与 15 票 A 节。**本票只实现传输，不得增删消息类型**；确有缺口先回填 spec 再改票。
- **前端职责边界**：只消费下行消息、只发上行消息；**不持有 Dashboard、不解析决议、不做路由**（spec『外观与分发』+ ADR-0005）。
- **观感对齐 Claude Code**：信息层次、按键提示、面板折叠；中文列宽用 `get-east-asian-width` 计算（不得用 `String.length`）。
- **许可红线**：`claude-code-best/claude-code` **无 License = 保留所有权利 → 只学交互模式，绝不复制代码**；Ink 本体从 npm 取（MIT）。
- **tkinter 边界**：仅首启配置窗口，前端不接管配置窗口。
- **命令与分发**：仍只有 `engine` 一条命令；`pipx` 分发。
- **兼容降级**：前端未接线/启动失败 → 后端自动退裸终端（`default_rendering` 路径，已在 15 票落地）。

## 已裁三点（Q71，2026-10-26 → spec v2.2『传输层』节）

1. **端口与发现 = 随机端口 + 握手文件**：后端 bind `127.0.0.1:0`，`{pid, port, thread_id, protocol_version, started_at}` 写 `<cwd>/.project-agent/handshake.json`；前端读文件连接，不固定端口（避免撞端口与多项目并行冲突）。会话结束删文件；残留文件按 pid 识别后忽略重试。
2. **前端产物 = 首次运行时下载**：wheel 保持纯 Python 不打包前端；首次运行下载到 `~/.project-agent/frontend/<version>/` 并校验；下载失败/用户拒绝 → 退终端降级渲染，不阻塞使用。
3. **断线重连 = 复用 thread_id 续跑**：重连带握手文件里的 thread_id，同 checkpointer 同 thread 继续，末态由 `_seed_state_from_checkpoint` 重建；不新开会话；显式放弃走 `--new-session`。

## 切片计划（每片一次汇报往返）

**片 1｜WebSocket 传输层（Python 侧）** ← 本片

- 新模块 `src/project_agent/transport.py`：`serve(handler, host="127.0.0.1", port=0)` 最薄包装 + `write_handshake` / `read_handshake` / `clear_handshake` 三个纯函数。
- 新模块 `src/project_agent/session.py`（或并入 transport）：把 ReplHost 的"文本 → 下行消息"抽成 **`SessionDriver.handle_input(text) -> list[dict]`**，使 stdin 与 WebSocket 共用同一实现。这是本片唯一结构改动。
- 依赖：`websockets` 加入 pyproject `dependencies`（MIT，venv 中已存在）。
- 验收 `tests/test_transport.py`：
  - `write_handshake` → `read_handshake` 往返（六字段齐、pid 校验）
  - 陈废握手文件（pid 不存在）被识别为失效
  - `SessionDriver.handle_input` 对斜杠命令返回 `notice`、对自由文本返回 `round_end`、对 `quit` 返回 `farewell`
  - 桩 socket 上跑一轮 `input → round_end` 消息序列
  - 红线哨兵：`transport.py` AST 顶层不 import 图/节点内部
- 硬约束：终端路径行为逐字不变（882 测试全绿为判据）。

**片 2｜Ink 前端骨架**
- 新目录 `frontend/`（TS + React 19 + Ink）；只实现：读握手文件连接、`ready` 横幅、`round_end` 渲染（复用后端 `lines`，**前端不重排文案**）、`prompt` 后采集输入、`farewell` 退出。
- 中文列宽 `get-east-asian-width`；宽窄终端自适应。

**片 3｜面板与按键**
- 按键提示行、状态面板折叠（`/status` 输出）、教学页提示可打开（`teach_page`）。

**片 4｜产物下载与 engine 并联**
- 首次运行下载前端产物到 `~/.project-agent/frontend/<version>/`；`engine` 拉起前端，找不到/下载失败 → 退裸终端。

**片 5｜收口（零新代码）**
- 合并、全量测试、勾票、spec 同步。

## 禁改清单

- `nodes.py` / `graph.py` / `routing.py` / `protocol.py` / `messages.py`：本票零改动（传输层不得反向依赖图；协议表不动）。
