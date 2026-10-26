# 17: 工具执行回路 —— actor 从文本指令桥升级为真实工具调用环

**Status:** done（2026-10-26 实现；989 测试绿零警告，ruff 干净）
**类型:** 工具票（spec v2.3『工具执行回路』）
**开票:** 2026-10-26

## 目标

actor 不再靠 `写入：`/`记录：` 文本桥落盘，而是**真实调用工具**：模型返回 `tool_calls` → 权限矩阵判定 → 执行 → 结果回灌 → 再循环。

## 五道工序（纯代码编排，零 LLM 判定）

1. **定义**：`tool_definitions(role)` 产出 OpenAI function schema，**只含该角色面内工具**（面外工具模型根本看不到）。
2. **调模型**：带 `tools` 请求 → 模型返回 `tool_calls`。
3. **判定**：`ToolRegistry.check` 第二道（防模型幻觉造工具名）；`DENY` → 回 `tool` 错误消息。
4. **执行**：分派到工具实现；异常捕获为错误消息回灌。
5. **回灌**：`ToolMessage` 追加历史，回到 2；无 `tool_calls` → 本轮终稿。

**封顶**：`MAX_TOOL_ITERATIONS=8`，超限转 `round` 交付并说明"工具轮次耗尽"。

## 工具实现表

| 工具 | 本票状态 |
|---|---|
| FileRead / Glob / Grep / FileWrite / FileEdit / DocScaffold | ✅ 本体落地（`tools/file_tools.py`） |
| Shell | ✅ 真实 subprocess 执行（过 `ShellPolicy` + 两旋钮） |
| NotepadAdd | ⚠️ 仍走"记录："文本桥（工具环分派未接，记欠账） |
| AskUserQuestion / SkillRecommend | ❌ 本体未实现（记欠账） |

## 三条硬约束

1. **权限在构造期**：schema 只含面内工具；`check` 是第二道。
2. **工具错误不中断环**：deny / 异常 / 超限折成 `tool` 消息回灌，模型自行改道。
3. **文本桥不删**：`写入：`/`记录：` 后置工序保留（无模型或不调工具时仍能落盘）。

## 顺带清掉的欠账

- **`decision_mode` 图内消费者**：`knobs.from_decision_mode` 接 `ShellTool`——`ai_review` 档静态放行、`manual` 档图内一律拒（无交互通道，fail-closed）。

## 验收测试清单

| 文件 | 断言 |
|---|---|
| `tests/test_tool_loop.py`（48 例） | 六工具本体行为、路径三重检查、FileEdit 唯一命中、DocScaffold 不覆盖、execute 分派、schema 与执行面一致、构造期面裁剪（AskAgent 看不到写工具）、调用环收敛/封顶/deny 回灌/异常回灌/幻觉工具拦截 |
| `tests/test_actor_tool_loop.py`（7 例） | actor 真走工具环并真实落盘；无工具能力模型行为不变；面外工具 deny；轮次耗尽文案；参数错误回灌 |
| `tests/test_decision_mode_consumers.py`（6 例） | `decision_mode` → 旋钮；`manual` 拒 shell、`ai_review` 放行安全命令；危险命令静态拦；文件工具两档都可用 |

## 三处真缺陷（均造红转绿）

1. **ShellPolicy 签名缺参**：构造时漏 `knobs` 与 `workspace_root`。
2. **成败判定靠字符串前缀猜**：`ToolLoop._invoke` 对 `Shell` 返回的字符串一律当成功——Shell 被拒时 `ToolResult.ok=False` 被吞。改为 runner 统一返回 `ToolResult`，成败由 `ok` 字段决定。
3. **`manual` 档静默回落审核档**：`knobs._DECISION_MODE_MAP` 只认 `human`，而 `config.py` 的 `decision_mode` 词表是 `ai_review|manual`——`manual` 被当未识别而回落 `ai_review`，**等于人工确认档失效**。按 `config.py` 词表补齐。

## 禁改清单

- `protocol.py` / `messages.py` / `graph.py` / `routing.py`：零改动。
- `tools/` 既有模块（registry/shell_policy/static_checker/approval/decision）：只加 `knobs.ask_level()` 方法，其余不动。
