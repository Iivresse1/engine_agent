"""REPL 宿主：终端 I/O、斜杠路由（零 LLM）、断点持有与渲染、/compact 手动压缩兜底、/ask-for-help 旁路。

10 票：/ask-for-help 旁路（AskBypass 独立历史，图外作答不写 state）。
11 票：输入进图前三层混合路由（hybrid_router.route_input）——仅 demo 构建中
（last_state.demo_phase=="building"）启用；报错回传融合进 demo_messages 并
demo_loop_count++，其余输入走既有 fusion_update 原路径。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from project_agent.ask_agent import AskBypass
from project_agent.config import IO
from project_agent.fusion import fusion_update
from project_agent.hybrid_router import route_input
from project_agent.nodes import run_compression_check

_BANNER = "Project Agent。输入 /help 查看命令。"
_FAREWELL = "再见"
_TERMINAL_NOTICE = "构建已完成（终态）。输入 /exit 退出。"
_COMPACT_NOT_ENABLED = "压缩未启用（需 --cheap-model 接线）"
_ASK_OUTSIDE_WORKFLOW = "仅项目工作流内可用"
_ASK_NOT_WIRED = "旁路未接线（需 model）"

# 命令按长度降序前缀匹配（spec『路由』：斜杠命令前缀匹配，零 LLM）
_COMMANDS = ("/help", "/status", "/compact", "/ask-for-help", "/skills", "/mode", "/exit")

# /mode 决策模式词表（Q19：AI 自动审核 / 全权人工；knobs.from_decision_mode 同源）
_MODE_LABELS: dict[str, str] = {
    "ai_review": "ai_review（AI 自动审核）",
    "manual": "manual（全权人工）",
}
_MODE_ALIASES: dict[str, str] = {
    "ai_review": "ai_review",
    "ai": "ai_review",
    "ai 自动审核": "ai_review",
    "自动": "ai_review",
    "manual": "manual",
    "全权人工": "manual",
    "人工": "manual",
}

_STATUS_FIELDS = (
    "task_brief",
    "build_way",
    "guidance_mode",
    "user_mode",
    "guidance_pref",
    "decision_mode",
    "skill_packs",
    "turn_end_reason",
)


class ReplHost:
    def __init__(
        self,
        app: Any,
        io: IO,
        thread_id: str,
        *,
        cheap_model: Any = None,
        shared_docs: Any = None,
        error_classifier: Any = None,
        ask_bypass: AskBypass | None = None,
    ) -> None:
        self._app = app
        self._io = io
        self._config = {"configurable": {"thread_id": thread_id}}
        self._last_state: dict[str, Any] = {}
        self._cheap_model = cheap_model
        self._shared_docs = shared_docs
        self._ask_bypass = ask_bypass
        # 11：窄分类兜底模型（ModelClient 形态；None → 层 3 默认 normal）
        self._error_classifier = error_classifier
        # /compact 产生的待并压缩批：下轮 invoke 携带进图（经 add_messages
        # reducer 归约——否则 checkpointer 里的历史永远未压）
        self._pending_compression: dict[str, Any] | None = None

    def run(self) -> None:
        self._io.write_line(_BANNER)
        while True:
            line = self._io.read_line()
            if line is None:  # EOF
                self._io.write_line(_FAREWELL)
                return
            text = line.strip()
            if not text:
                continue
            if text.startswith("/"):
                if self._dispatch(text):
                    return
                continue
            self._run_round(text)

    def _dispatch(self, text: str) -> bool:
        """斜杠命令前缀匹配分发（零 LLM）。返回 True 表示退出。"""
        command = next((c for c in sorted(_COMMANDS, key=len, reverse=True) if text.startswith(c)), None)
        if command == "/exit":
            self._io.write_line(_FAREWELL)
            return True
        if command == "/help":
            self._io.write_line("可用命令：" + " ".join(_COMMANDS))
            return False
        if command == "/status":
            self._status()
            return False
        if command == "/compact":
            self._compact()
            return False
        if command == "/ask-for-help":
            self._ask_for_help(text)
            return False
        if command == "/mode":
            self._mode(text)
            return False
        if command == "/skills":
            self._skills(text)
            return False
        self._io.write_line(f"未知命令 {text}。可用命令：{' '.join(_COMMANDS)}")
        return False

    def _mode(self, text: str) -> None:
        """/mode：查/改决策模式（用户故事 3——运行时配置入口）。

        无参 → 显示当前与可选；有效值（ai_review|manual|中文别名）→ 更新
        REPL 持有态的 decision_mode（ShellTool 审批档接线票消费）；无效 → 提示。
        """
        current = str(self._last_state.get("decision_mode") or "")
        raw_arg = text[len("/mode"):].strip()
        arg = raw_arg.lower()
        if not arg:
            options = "、".join(_MODE_LABELS.values())
            self._io.write_line(f"当前决策模式：{current or '未设置'}。可选：{options}")
            return
        new_mode = _MODE_ALIASES.get(arg) or _MODE_ALIASES.get(raw_arg)
        if new_mode is None:
            options = "、".join(_MODE_LABELS.values())
            self._io.write_line(f"未识别模式 {raw_arg!r}。当前：{current or '未设置'}。可选：{options}")
            return
        self._last_state["decision_mode"] = new_mode
        self._io.write_line(f"决策模式已更新：{new_mode}")

    def _skills(self, text: str) -> None:
        """/skills：查/改技能包清单（用户故事 3——运行时配置入口）。

        无参 → 列出已选包；add {name} → 追加（去重）；remove {name} → 移除。
        """
        packs = list(self._last_state.get("skill_packs") or [])
        arg = text[len("/skills"):].strip()
        if not arg:
            self._io.write_line(
                f"已选技能包：{', '.join(packs) if packs else '（无）'}"
            )
            return
        sub, _, name = arg.partition(" ")
        if sub == "add" and name.strip():
            pack = name.strip()
            if pack not in packs:
                packs.append(pack)
                self._last_state["skill_packs"] = packs
                self._io.write_line(f"已添加技能包：{pack}")
            else:
                self._io.write_line(f"技能包 {pack} 已在清单中。")
        elif sub == "remove" and name.strip():
            pack = name.strip()
            if pack in packs:
                packs.remove(pack)
                self._last_state["skill_packs"] = packs
                self._io.write_line(f"已移除技能包：{pack}")
            else:
                self._io.write_line(f"技能包 {pack} 不在清单中。")
        else:
            self._io.write_line("用法：/skills [add|remove] {包名}")

    def _ask_for_help(self, text: str) -> None:
        """10 票旁路：/ask-for-help {question}——AskBypass 独立历史作答。

        仅项目工作流内（build_way 已设）可用；不进主图不写 state。
        """
        question = text[len("/ask-for-help"):].strip()
        if not self._last_state.get("build_way"):
            self._io.write_line(_ASK_OUTSIDE_WORKFLOW)
            return
        if self._ask_bypass is None:
            self._io.write_line(_ASK_NOT_WIRED)
            return
        if not question:
            self._io.write_line("用法：/ask-for-help {问题}")
            return
        self._io.write_line(self._ask_bypass.ask(question))

    def _compact(self) -> None:
        """/compact 手动兜底（08 票）：立即触发等价压缩（manual=True）。

        仍守 3 轮保护与两包上限；压缩结果（重排后消息批 + compacted_rounds）
        并入 REPL 持有状态——下轮 invoke 携带；不进主图。
        """
        if self._cheap_model is None:
            self._io.write_line(_COMPACT_NOT_ENABLED)
            return
        updates = run_compression_check(
            messages=self._last_state.get("actor_messages") or [],
            model=None,
            cheap_model=self._cheap_model,
            thread_id=str(self._config.get("configurable", {}).get("thread_id", "")),
            shared_docs=self._shared_docs,
            notes_version=int(self._last_state.get("notes_version") or 0),
            manual=True,
        )
        if updates is None:
            self._io.write_line("无可压缩轮次（3 轮保护或无候选）。")
            return
        self._last_state.update(updates)
        self._pending_compression = updates
        packs = updates.get("compacted_rounds") or []
        covered = sum(end - start + 1 for start, end in packs)
        self._io.write_line(f"已压缩 {covered} 轮（{len(packs)} 包）；磁盘【R#】原文不受影响。")

    def _run_round(self, text: str) -> None:
        # 11：demo 构建中的输入先过三层混合路由（斜杠已在 run() 前分流）
        if self._last_state.get("demo_phase") == "building":
            route = route_input(
                text,
                last_state=self._last_state,
                error_classifier=self._error_classifier,
            )
            if route == "error_return":
                # 报错回传：融合进 demo_messages 进修复环；demo 环计数++（封顶 5）
                self._invoke_round(
                    {
                        "demo_messages": [HumanMessage(content=text)],
                        "demo_loop_count": int(
                            self._last_state.get("demo_loop_count") or 0
                        )
                        + 1,
                    }
                )
                return

        update = fusion_update(self._last_state, text)
        if not update:
            # FINISHED 终态（01 欠账 b）：不再融合不再 invoke
            self._io.write_line(_TERMINAL_NOTICE)
            return
        if self._pending_compression is not None:
            # 待并压缩批先行：头部单包/RemoveMessage 与新输入一起进图，
            # add_messages reducer 归约出压缩后历史（一次性，随后清空）
            pending = self._pending_compression
            self._pending_compression = None
            merged_batch = list(pending.get("actor_messages") or [])
            merged_batch.extend(update.get("actor_messages") or [])
            update = dict(pending)
            update["actor_messages"] = merged_batch
        self._invoke_round(update)

    def _invoke_round(self, update: dict[str, Any]) -> None:
        result = dict(self._app.invoke(update, self._config))
        self._last_state = result

        reason = result.get("turn_end_reason") or "未记录"
        payload = result.get("turn_end_payload") or {}
        self._io.write_line(f"断点 · {reason}")
        for key, value in payload.items():
            self._io.write_line(f"  {key}: {value}")

    def _status(self) -> None:
        if not self._last_state:
            self._io.write_line("尚无会话状态。")
            return
        for field in _STATUS_FIELDS:
            self._io.write_line(f"{field}: {self._last_state.get(field, '')}")
