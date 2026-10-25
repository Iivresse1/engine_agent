# 16: UX-3 前端与传输 —— WebSocket 传输 + Ink 前端 + Bun 打包

**Status:** ready（spec v2.1 已定契约，实现未开；本票由 spec 翻译，不做新设计）
**类型:** UX 实现票（ADR-0005 双运行时）
**开票:** 2026-10-26
**依赖:** 15 票（协议消息表 + 翻译层已落）

## 目标

把 `messages.py` 的消息表接到真实传输与真实观感上：后端起 WebSocket 服务，前端用 Ink 渲染并采集按键。

## 已由 spec 钉死的部分（不得再设计）

- **消息表与形状**：见 spec v2.1『协议消息层』与 15 票 A 节。**本票只实现传输，不得增删消息类型**；确有缺口先回填 spec 再改票。
- **前端职责边界**：只消费下行消息、只发上行消息；**不持有 Dashboard、不解析决议、不做路由**（spec『外观与分发』+ ADR-0005）。
- **观感对齐 Claude Code**：信息层次、按键提示、面板折叠；中文列宽用 `get-east-asian-width` 计算（不得用 `String.length`）。
- **许可红线**：`claude-code-best/claude-code` **无 License = 保留所有权利 → 只学交互模式，绝不复制代码**；Ink 本体从 npm 取（MIT）。
- **tkinter 边界**：仅首启配置窗口，前端不接管配置窗口。
- **命令与分发**：仍只有 `engine` 一条命令；`pipx` 分发。
- **兼容降级**：前端未接线/启动失败 → 后端自动退裸终端（`default_rendering` 路径，已在 15 票落地）。

## 切片计划（每片一次汇报往返）

**片 1｜WebSocket 传输层（Python 侧）**
- 新模块 `src/project_agent/transport.py`：`serve(app, host, port)` 最薄包装——收 `input`/`quit` → 调 `ReplHost` 已抽出的分发函数 → 回 `round_end`/`notice`/`farewell`。
- 关键：**把 ReplHost 的"文本 → 下行消息"逻辑抽成纯函数**（`handle_input(text) -> list[down_message]`），使 stdin 与 WebSocket 共用同一实现。这是本片唯一的结构改动，且必须不改变终端路径行为（882 测试全绿为判据）。
- 验收：`tests/test_transport.py` 用桩 socket 断言消息序列；红线哨兵——`transport.py` 顶层不 import 网络库之外的东西、不 import 图内部。

**片 2｜Ink 前端骨架**
- 新目录 `frontend/`（TS + React 19 + Ink）；只实现：连接、`ready` 横幅、`round_end` 渲染（复用后端给的 `lines`，**前端不重排文案**）、`prompt` 后采集输入、`farewell` 退出。
- 中文列宽 `get-east-asian-width`；宽窄终端自适应。

**片 3｜面板与按键**
- 按键提示行、状态面板折叠（`/status` 输出）、教学页提示可打开（`teach_page`）。

**片 4｜Bun 打包与 engine 命令并联**
- `engine` 启动时拉起前端（找不到前端产物则退裸终端）；`pipx install` 后单命令可用。

**片 5｜收口（零新代码）**
- 合并、全量测试、勾票、spec 同步（若片 1 抽函数导致 spec 描述需更新）。

## 未定需先裁的点（**不得在实现中擅自决定**）

1. 端口与发现机制（固定端口 / 随机端口 + 握手文件）。
2. 前端产物如何随 Python 包分发（打包进 wheel / 首次运行下载）。
3. 断线重连后的会话恢复语义（复用 thread_id 续跑 vs 新会话）。

以上三点**实现前必须先写进 spec**（Q68 纪律：新裁定先入 spec 再开票）。
