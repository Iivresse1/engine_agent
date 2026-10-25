# 15: UX-2 协议消息层 —— 前后端唯一主接缝的契约与翻译层

**Status:** done（2026-10-26 第一片实现；882 测试绿零警告，ruff 干净）
**类型:** UX 契约票（ADR-0005 接缝，spec v2.1『协议消息层』）
**开票:** 2026-10-26

**已实现（第一片）**：
- `src/project_agent/messages.py`：`MessageSpec` / `DOWN_MESSAGES`(6) / `UP_MESSAGES`(2) 消息表；`encode` / `decode` 形状校验（缺字段、多字段、错类型、未知 type、bool 冒充 int 全拦）；`default_rendering` 六类下行终端折叠；`round_end_message` 便捷构造。
- REPL 三处接入同一份折叠逻辑：开场序列（`ready`）、轮终交付（`round_end`）、退出/EOF（`farewell`）——前端未接线时行为与 v2.0 完全一致（兼容降级落地形态）。
- 冒烟顺带修掉一处 spec 契约缺陷：`choice:build_way` / `choice:proposal` / `docs_done` 断点此前整 dict 平铺，**未走三层渲染**；新增 `rendering.render_breakpoint_lines` 按 reason 分发（question → 问题三层；决议类 → 主体/解释/编号选项/推荐+理由；其余平铺）。
- 测试 881→882（+26 新：test_messages 25 + 分发 1；3 例 REPL 断言随渲染升级适配）。
- 红线哨兵：AST 断言 `messages.py` 不 import 任何图/节点/模型/REPL/langgraph 模块（协议层反向依赖图 = 倒退）。

**余下（未实现，见 spec『已知欠账』）**：WebSocket 传输层、后端服务化进程模型、断线重连与会话恢复语义。

## 目标

把"后端裸终端"与"未来 Ink 前端"抽成**同一份协议**的两个消费者——前端引入时零图改动、零状态复制。

## 钉死的设计裁定（实现零决策）

### A. 消息表（表即契约，与断点协议同等级）

| 方向 | type | 字段 | 语义 |
|---|---|---|---|
| down | ready | banner, opening_prompt | 会话就绪 |
| down | prompt | awaiting | 请求输入 |
| down | round_end | reason, payload, lines | 断点交付（lines = 终端降级渲染行） |
| down | notice | text | 即时提示 |
| down | teach_page | path, round | 教学页已生成 |
| down | farewell | text | 会话终止 |
| up | input | text | 一条自由文本（含斜杠原文） |
| up | quit | — | 请求退出 |

四条硬约束：**信封只一层**（`{"type": ...}`，无嵌套、无版本协商）；**后端裸终端仍可用**（`default_rendering` 是平行消费者，不是"简化模式"）；**协议层零业务逻辑**（不 import 图/节点/模型）；**决议语义仍走自由文本**（payload 原样透传，前端不得解释，input 永远是纯文本）。

### B. 字段类型钉死

`payload` = dict；`lines` = list[str]；`round` = int（**bool 不算 int**）；其余全部 str。任何违反 → `MessageError`（异常消息须含中文类别词，测试按子串断言）。

### C. 渲染分发（rendering.py）

`render_breakpoint_lines(reason, payload, ansi=None)` 是 REPL 与协议层共用唯一分发点：
- `question` → `render_question_payload`（三层）
- `choice:build_way` / `choice:proposal` / `docs_done` → `render_choice_payload`（主体加粗 → 解释缩进 → 编号选项 → `推荐：` + 独立 `推荐理由：` 行）
- 其余 → 逐字段 `  key: value` 平铺

**理由必须独立成行**：推荐串自带" —— "说明时仍保留 ≤20 字代码截断理由（可读性契约要求"推荐必附理由"，不可被推荐串内嵌说明吞掉）。

## 验收测试清单

| 文件 | 断言 |
|---|---|
| `tests/test_messages.py::test_down_messages_match_spec_table` | 6 类下行 kind 与字段序 = spec 表 |
| `::test_up_messages_match_spec_table` | 2 类上行同上 |
| `::test_encode_round_end_envelope_is_single_layer` | 信封恰好 4 键，无嵌套 |
| `::test_encode_rejects_missing_field` / `_unknown_field` / `_unknown_kind` / `_wrong_type` | 四类形状违规各报 `MessageError` |
| `::test_round_end_payload_must_be_dict` / `_lines_must_be_list_of_str` | 容器类型校验 |
| `::test_teach_page_round_must_be_int_and_reject_bool` | bool 冒充 int 被拒 |
| `::test_decode_*`（5 例） | 上行解码：正常 / 无字段 / 未知 type / 缺字段 / 多字段 / 非 mapping |
| `::test_default_rendering_*`（5 例） | 六类下行的终端折叠逐行断言 |
| `::test_render_breakpoint_lines_dispatches_by_reason` | 决议类走三层、round 类平铺 |
| `::test_repl_opening_sequence_uses_ready_message` | REPL 开场四行 = ready 折叠 + farewell |
| `::test_repl_round_end_matches_message_layer` | REPL 断点首行 = 协议层折叠结果 |
| `::test_messages_module_has_no_graph_dependency` | 红线哨兵（AST import 白名单） |

## 禁改清单

- `nodes.py` / `graph.py` / `routing.py` / `protocol.py`：本轮**零改动**（协议层不得反向依赖；断点协议表不动）。
- 前端、传输层、进程模型：不属本票。
