"""骨架节点：ask_tasks / build_ways（choice:build_way 断点流）/ guidance_trigger / planner。

全部可重入：已写字段不再改写（断点续跑下轮重进不重复副作用）。
build_ways 由 make_build_ways_node(model) 工厂构造——model=None 走静态推荐。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from langchain_core.messages import AIMessage, HumanMessage

from project_agent.onboarding import (
    QUESTIONNAIRE,
    interpret_answer,
    next_unset_field,
    question_for,
)
from project_agent.protocol import Role, TurnEndReason, validate_payload
from project_agent.routing import _todos_all_completed, derive_actor_config
from project_agent.shared_docs import SharedDocs


# 四种构建方式（GLOSSARY『build_ways』）：标签即 choice payload 的 options
BUILD_WAY_OPTIONS: list[str] = ["对话", "轻 grill", "简化文档", "完整文档"]
_WAY_BY_LABEL: dict[str, str] = {
    "对话": "way1",
    "轻 grill": "way2",
    "简化文档": "way3",
    "完整文档": "way4",
}

# 静态默认（model=None 或模型输出垃圾）
_STATIC_RECOMMENDATION = "简化文档"
_STATIC_REASON = "个人作品有沉淀不臃肿"


def _STATIC_RECOMMENDATION_LABEL() -> str:
    return _STATIC_RECOMMENDATION

# 解释引擎关键词序（前缀优先防误吞）
_BUILD_WAY_KEYWORDS: list[tuple[str, str]] = [
    ("完整", "way4"),
    ("简化", "way3"),
    ("轻", "way2"),
    ("对话", "way1"),
    ("聊天", "way1"),
]

# 序号匹配：裸 ^[\W_]*([1-9])[\W_]*$ 或语境 (?:第|选项|方式|选)\s*([1-9])
# \W 不含汉字——"做个 2048 游戏"这类自由文本不会误中。
_BARE_INDEX = re.compile(r"^[\W_]*([1-9])[\W_]*$")
_CONTEXTUAL_INDEX = re.compile(r"(?:第|选项|方式|选)\s*([1-9])")


def _interpret_build_way(text: str | None, recommended: str | None = None) -> str | None:
    """解释自由文本 → way1–way4；解释不了返回 None。

    优先级：wayN 子串直配 → 序号（裸/语境）→ 关键词 → "推荐"按推荐。
    """
    if not text:
        return None
    lowered = text.lower()
    for n in range(1, 5):
        if f"way{n}" in lowered:
            return f"way{n}"
    m = _BARE_INDEX.match(text) or _CONTEXTUAL_INDEX.search(text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 4:
            return f"way{n}"
    for keyword, way in _BUILD_WAY_KEYWORDS:
        if keyword in text:
            return way
    if "推荐" in text and recommended is not None:
        way = _WAY_BY_LABEL.get(recommended)
        if way is not None:
            return way
    return None


def _choice_breakpoint(
    recommendation: str, reason: str
) -> dict[str, Any]:
    payload = validate_payload(
        TurnEndReason.CHOICE_BUILD_WAY,
        {
            "options": list(BUILD_WAY_OPTIONS),
            "recommendation": recommendation,
            "recommendation_reason": reason[:20],
        },
    )
    return {"turn_end_reason": TurnEndReason.CHOICE_BUILD_WAY.value, "turn_end_payload": payload}


def _latest_human_text(state: Mapping[str, Any]) -> str | None:
    for msg in reversed(list(state.get("actor_messages") or [])):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _first_human_text(state: Mapping[str, Any]) -> str | None:
    for msg in list(state.get("actor_messages") or []):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _round_end(round_output: str, state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """写 round 断点：轮产出 + todo 板（spec 断点协议表 round 行 payload）。"""
    payload = validate_payload(
        TurnEndReason.ROUND,
        {"round_output": round_output, "todo_board": _todo_board(state)},
    )
    return {"turn_end_reason": TurnEndReason.ROUND.value, "turn_end_payload": payload}


def _todo_board(state: Mapping[str, Any] | None) -> list[str]:
    """三态 todo 板渲染（01 骨架：工作流级 todos 通常为空 → 空板）。"""
    board: list[str] = []
    for item in (state or {}).get("todos") or []:
        if isinstance(item, dict):
            content = str(item.get("content", ""))
            status = str(item.get("status", "pending"))
            board.append(f"{status}: {content}")
    return board


def _question_breakpoint(spec, hint: bool = False) -> dict[str, Any]:
    """question 断点：问题文本 + 选项 + 提问角色（spec 断点协议表 question 行）。"""
    text = spec.question_text
    if hint and spec.novice_hint:
        text = f"{text}{spec.novice_hint}"
    payload = validate_payload(
        TurnEndReason.QUESTION,
        {
            "question_text": text,
            "options": list(spec.options),
            "asker": Role.ACTOR.value,
        },
    )
    return {
        "turn_end_reason": TurnEndReason.QUESTION.value,
        "turn_end_payload": payload,
        "awaiting_input_from": Role.ACTOR.value,
    }


def ask_tasks_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """首启两层：问卷四问 → task_brief 一次写定。

    - task_brief 已设 → {}（一次写定 + 01 遗留会话直达）
    - 上一轮 turn_end_reason=="question"：最新人类消息=当前题答案——解释成功
      写字段；四问全齐 → task_brief 从**首条**人类消息（原始想法）写定+round_end；
      不可解释 → 重问本题（幂等零副作用）
    - 非 question 后续 → 问第一未设题（首轮用户想法绝不当答案解释）
    - 判"未设"：value is None or value == ""（skill_packs=[] 合法已设）
    """
    if state.get("task_brief"):
        return {}

    def _ask(field: str, dashboard: Mapping[str, Any] | None = None) -> dict[str, Any]:
        spec = question_for(field)
        probe = dashboard if dashboard is not None else state
        hint = field == "guidance_pref" and probe.get("user_mode") == "novice"
        return _question_breakpoint(spec, hint=hint)

    def _unset(dashboard: Mapping[str, Any]) -> str | None:
        return next_unset_field(dashboard)

    if state.get("turn_end_reason") == TurnEndReason.QUESTION.value:
        current = _unset(state)
        answer = _latest_human_text(state)
        if current is not None and answer is not None:
            spec = question_for(current)
            value = interpret_answer(spec, answer)
            if value is not None:
                updated: dict[str, Any] = {current: value}
                probe = dict(state)
                probe.update(updated)
                nxt = _unset(probe)
                if nxt is None:
                    # 四问全齐：task_brief 从首条人类消息（原始想法）写定
                    brief = _first_human_text(state)
                    if brief:
                        return {
                            **updated,
                            "task_brief": brief,
                            **_round_end(f"任务简报已记录：{brief}", state),
                        }
                return {**updated, **_ask(nxt, probe)} if nxt is not None else updated
        # 不可解释或无答案：重问当前题（幂等零副作用）
        target = current if current is not None else _unset(state)
        if target is not None:
            return _ask(target)

    # 非 question 后续 / 首轮：问第一未设题
    field = _unset(state)
    if field is not None:
        return _ask(field)
    # 问卷已齐但简报未写（异常兜底）：从首条人类消息写定
    brief = _first_human_text(state)
    if brief:
        return {"task_brief": brief, **_round_end(f"任务简报已记录：{brief}", state)}
    return {}


def make_build_ways_node(model: Any = None):
    """build_ways 节点工厂：choice:build_way 断点流 + 决议通道消费。

    - build_way 已设 → {}（可重入零副作用）
    - resolution_inputs 非空 → 消费 pending[-1]：解释成功 → 写 build_way +
      清空通道 + round_end("构建方式已定：wayN")；不可解释 → 清空 + 复用上轮
      turn_end_payload（校验通过才复用）重发 choice——零重复 ModelClient 调用
    - 无 pending → 发 choice 断点：model 驱动推荐或静态默认
    """

    def _recommended_from_payload(payload: Any) -> str | None:
        if not isinstance(payload, Mapping):
            return None
        value = payload.get("recommendation")
        return value if isinstance(value, str) else None

    def _model_recommendation(state: Mapping[str, Any], config: Any) -> tuple[str, str]:
        brief = str(state.get("task_brief") or "")
        user_mode = str(state.get("user_mode") or "")
        prompt = (
            f"任务简报：{brief}\n"
            f"用户编程基础：{user_mode}\n"
            "四种构建方式：1=对话 2=轻 grill 3=简化文档 4=完整文档\n"
            "推荐其一并给一句话理由（≤20 字）。输出格式：选择|理由"
        )
        thread_id = ""
        if isinstance(config, Mapping):
            configurable = config.get("configurable") or {}
            if isinstance(configurable, Mapping):
                thread_id = str(configurable.get("thread_id") or "")
        result = model.complete(
            [{"role": "user", "content": prompt}],
            role=Role.ACTOR.value,
            thread_id=thread_id,
        )
        text = str(result.text)
        choice, _, reason = text.partition("|")
        way = _interpret_build_way(choice.strip())
        if way is None:
            return _STATIC_RECOMMENDATION_LABEL(), _STATIC_REASON
        label = _LABEL_BY_WAY[way]
        reason = reason.strip() or _STATIC_REASON
        return label, reason

    def build_ways_node(
        state: Mapping[str, Any], config: Optional[Mapping[str, Any]] = None
    ) -> dict[str, Any]:
        if state.get("build_way"):
            return {}

        pending = state.get("resolution_inputs") or []
        if pending:
            text = str(pending[-1])
            recommended = _recommended_from_payload(state.get("turn_end_payload"))
            way = _interpret_build_way(text, recommended=recommended)
            if way is not None:
                return {
                    "build_way": way,
                    "resolution_inputs": [],
                    **_round_end(f"构建方式已定：{way}", state),
                }
            # 不可解释：清空通道 + 复用上轮 payload 重发 choice（可重入零副作用）
            last_payload = state.get("turn_end_payload")
            reuse = _recommended_from_payload(last_payload) is not None
            if reuse and isinstance(last_payload, Mapping):
                try:
                    payload = validate_payload(
                        TurnEndReason.CHOICE_BUILD_WAY, dict(last_payload)
                    )
                except Exception:
                    payload = None
            else:
                payload = None
            if payload is not None:
                return {
                    "resolution_inputs": [],
                    "turn_end_reason": TurnEndReason.CHOICE_BUILD_WAY.value,
                    "turn_end_payload": payload,
                }
            return {"resolution_inputs": [], **_static_choice()}

        if model is not None:
            recommendation, reason = _model_recommendation(state, config)
        else:
            recommendation, reason = _STATIC_RECOMMENDATION, _STATIC_REASON
        return _choice_breakpoint(recommendation, reason)

    return build_ways_node


def _static_choice() -> dict[str, Any]:
    return _choice_breakpoint(_STATIC_RECOMMENDATION, _STATIC_REASON)


# —— 07 终裁 C：way4 三方案并行节点 ——


_FALLBACK_PROPOSALS: list[str] = [
    "轻量方案：默认技术栈",
    "均衡方案：常用技术栈",
    "完整方案：企业级技术栈",
]

# 决议关键词（匹配 proposal_set 文本；序（轻量/均衡/完整）= idx）
_PROPOSAL_KEYWORDS: list[tuple[str, int]] = [
    ("轻量", 0),
    ("均衡", 1),
    ("完整", 2),
]


def _parse_proposals(text: str) -> list[str]:
    """模型输出解析：非空行且含"|"（"方案名|一句话摘要"格式）≤3 行；
    全不符/空 → []（调用方走兜底三案）。"""
    lines = [
        line.strip()
        for line in str(text).splitlines()
        if line.strip() and "|" in line
    ]
    return lines[:3]


def _proposal_breakpoint(proposal_set: list[str]) -> dict[str, Any]:
    """choice:proposal 断点：proposal_summaries 受控形状。"""
    payload = validate_payload(
        TurnEndReason.CHOICE_PROPOSAL, {"proposal_summaries": list(proposal_set)}
    )
    return {
        "proposal_set": list(proposal_set),
        "turn_end_reason": TurnEndReason.CHOICE_PROPOSAL.value,
        "turn_end_payload": payload,
    }


def _interpret_proposal(
    text: str | None, proposal_set: list[str]
) -> int | None:
    """解释自由文本 → 方案 idx；解释不了返回 None。

    优先级：序号（裸 ^[\\W_]*[1-9][\\W_]*$ / 语境 (?:第|选项|方案|方式|选)\\s*[1-9]，
    同 02 的 _interpret 序法）→ 关键词匹配方案文本（"轻量"→0/"均衡"→1/
    "完整"→2，含兜底案名）。
    """
    if not text:
        return None
    m = _BARE_INDEX.match(text) or _PROPOSAL_CONTEXTUAL_INDEX.search(text)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(proposal_set):
            return idx
    for keyword, idx in _PROPOSAL_KEYWORDS:
        if keyword in text and idx < len(proposal_set):
            return idx
    return None


_PROPOSAL_CONTEXTUAL_INDEX = re.compile(r"(?:第|选项|方案|方式|选)\s*([1-9])")


def make_proposals_node(model: Any = None):
    """三方案并行节点工厂（07 终裁 C，way4 专属）。

    - selected_proposal 已设 → {}（可重入零副作用）
    - resolution_inputs 非空 → 解释：序号（裸/语境）→ selected_proposal=idx；
      关键词匹配方案文本；成功 → 写 selected_proposal + 通道清空 +
      round_end("方案已选定：{摘要}")；无匹配 → 清空 + 复用上轮 payload
      校验后重发（零 model 调用）；payload 不可复用 → 兜底三案重发
    - 无 pending：调 ModelClient（role=actor，thread_id 出 config）产三行方案；
      解析失败/空 → 兜底三案；写 proposal_set + choice:proposal 断点
    - model=None → 静态兜底三案（零调用）
    """

    def _model_proposals(state: Mapping[str, Any], config: Any) -> list[str]:
        brief = str(state.get("task_brief") or "")
        user_mode = str(state.get("user_mode") or "")
        prompt = (
            f"任务简报：{brief}\n"
            f"用户编程基础：{user_mode}\n"
            "请给出三套构建方案（技术栈 × 复杂度取舍维度），每行格式：方案名|一句话摘要，共三行。"
        )
        result = model.complete(
            [{"role": "user", "content": prompt}],
            role=Role.ACTOR.value,
            thread_id=_thread_id_from(config),
        )
        parsed = _parse_proposals(str(result.text))
        return parsed if parsed else list(_FALLBACK_PROPOSALS)

    def _reuse_payload(state: Mapping[str, Any]) -> dict[str, Any] | None:
        """复用上轮 turn_end_payload（校验通过才复用；同 build_ways 模式）。"""
        last_payload = state.get("turn_end_payload")
        if not isinstance(last_payload, Mapping):
            return None
        try:
            return validate_payload(
                TurnEndReason.CHOICE_PROPOSAL, dict(last_payload)
            )
        except Exception:
            return None

    def proposals_node(
        state: Mapping[str, Any], config: Optional[Mapping[str, Any]] = None
    ) -> dict[str, Any]:
        if state.get("selected_proposal") is not None:
            return {}

        pending = state.get("resolution_inputs") or []
        if pending:
            text = str(pending[-1])
            proposal_set = [
                str(item) for item in (state.get("proposal_set") or [])
            ]
            idx = _interpret_proposal(text, proposal_set or list(_FALLBACK_PROPOSALS))
            if idx is not None:
                summary = (
                    proposal_set[idx]
                    if proposal_set and idx < len(proposal_set)
                    else _FALLBACK_PROPOSALS[idx]
                )
                return {
                    "selected_proposal": idx,
                    "resolution_inputs": [],
                    **_round_end(f"方案已选定：{summary}", state),
                }
            # 无匹配：清空通道 + 复用上轮 payload 重发（零 model 调用）
            payload = _reuse_payload(state)
            if payload is not None:
                return {
                    "resolution_inputs": [],
                    "turn_end_reason": TurnEndReason.CHOICE_PROPOSAL.value,
                    "turn_end_payload": payload,
                }
            return {
                "resolution_inputs": [],
                **_proposal_breakpoint(list(_FALLBACK_PROPOSALS)),
            }

        if model is not None:
            proposal_set = _model_proposals(state, config)
        else:
            proposal_set = list(_FALLBACK_PROPOSALS)
        return _proposal_breakpoint(proposal_set)

    return proposals_node


_LABEL_BY_WAY: dict[str, str] = {way: label for label, way in _WAY_BY_LABEL.items()}


def guidance_trigger_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """纯配置映射写 guidance_mode 三态（spec 节点表：只写 guidance_mode，不写 turn_end）。"""
    from project_agent.onboarding import guidance_mode_mapping

    mode = guidance_mode_mapping(
        state.get("build_way"),
        state.get("guidance_pref"),
        state.get("user_mode"),
    )
    return {"guidance_mode": mode}


# 05：planner todos 模板（按构建方式；中文动词短语，测试断言结构非文案）
_PLANNER_TEMPLATES: dict[str, list[str]] = {
    "way1": ["梳理需求边界", "推进对话任务"],
    "way2": ["梳理需求边界", "产出一页纸方案"],
    "way3": ["梳理需求边界", "编写 README", "编写 TODO", "生成目录树"],
    "way4": ["梳理需求边界", "搭建文档框架", "填写核心文档"],
}
_PLANNER_FALLBACK = "确认构建范围"


def planner_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """planner：读 build_way 产 todos（全 pending 工作流级清单）。

    - todos 空 → 新计划：todos + main_loop_count=0
    - todos 已设 → 重规划：todos 全新 pending + main_loop_count 保留
      （旧值 >=5 → 清零开新循环：耗尽恢复路径）
    - round_end："已列出 N 项计划"（todo_board 渲染新板三态）
    """
    way = str(state.get("build_way") or "")
    contents = list(_PLANNER_TEMPLATES.get(way, [])) or [_PLANNER_FALLBACK]
    todos = [{"content": content, "status": "pending"} for content in contents]
    if state.get("todos"):
        count = int(state.get("main_loop_count") or 0)
        main_loop_count = 0 if count >= 5 else count
    else:
        main_loop_count = 0
    return {
        "todos": todos,
        "main_loop_count": main_loop_count,
        **_round_end(f"已列出 {len(todos)} 项计划", {**state, "todos": todos}),
    }


def _pending_count(todos: Any) -> int:
    return sum(
        1
        for item in todos or []
        if isinstance(item, dict) and item.get("status") != "completed"
    )


_SCAFFOLD_HINT = (
    "\n构建方式为完整文档：先以占位框架落盘各交付物（每份文档标题+空节），随后逐轮 grilling 填充。"
)


def context_assembler_node(
    state: Mapping[str, Any],
    shared_docs: Optional[SharedDocs] = None,
) -> dict[str, Any]:
    """context_assembler：写 assembled_context（每轮整覆写，state key 无 reducer）。

    读 current_scope / todos / guidance_mode / build_way；不写任何消息。

    07 终裁 C（DocScaffold）：shared_docs 非 None 且 build_way=="way4" 且
    工作区无交付物框架（首个文档不存在）→ system 末尾追加框架先行说明行；
    框架已存在则不追加（首轮落框架后自然消失）。
    """
    todos = state.get("todos") or []
    system = (
        f"你是构建 agent。当前方式 {state.get('build_way') or ''}，"
        f"指引 {state.get('guidance_mode') or ''}，"
        f"待办 {_pending_count(todos)} 项"
    )
    if (
        state.get("build_way") == "way4"
        and shared_docs is not None
        and not _scaffold_exists(shared_docs)
    ):
        system = system + _SCAFFOLD_HINT
    updates: dict[str, Any] = {
        "assembled_context": {
            "system": system,
            "todo_board": _todo_board(state),
            "scope": str(state.get("current_scope") or "main"),
        }
    }
    return updates


def _scaffold_exists(shared_docs: SharedDocs) -> bool:
    """工作区是否已有交付物框架：DELIVERABLE_SETS['way4'] 首个文档存在即视为已落。"""
    from project_agent.deliverables import DELIVERABLE_SETS

    for name in DELIVERABLE_SETS["way4"]:
        if (shared_docs.root / name).exists():
            return True
    return False


def _thread_id_from(config: Any) -> str:
    thread_id = ""
    if isinstance(config, Mapping):
        configurable = config.get("configurable") or {}
        if isinstance(configurable, Mapping):
            thread_id = str(configurable.get("thread_id") or "")
    return thread_id


def _actor_model_messages(
    state: Mapping[str, Any]
) -> list[dict[str, str]]:
    """隔离红线（验收 7）：messages 只含 system + actor 私有历史——绝不掺其他角色历史。"""
    context = state.get("assembled_context") or {}
    messages: list[dict[str, str]] = [
        {"role": "system", "content": str(context.get("system") or "")}
    ]
    for msg in state.get("actor_messages") or []:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": str(msg.content)})
    return messages


def _check_todos(todos: Any, response_text: str) -> list[Any]:
    """todos 勾选：pending/in_progress 项若 f"完成：{content}" 是响应子串→completed。

    精确匹配，匹配不到跳过；返回整列表（todos 无 reducer 整覆写）。
    """
    new_todos: list[Any] = []
    for item in todos or []:
        if (
            isinstance(item, dict)
            and item.get("status") in ("pending", "in_progress")
            and f"完成：{item.get('content', '')}" in response_text
        ):
            new_todos.append({**item, "status": "completed"})
        else:
            new_todos.append(item)
    return new_todos


_ACTOR_SKELETON_NOTICE = "主环待真模型接入（05 骨架）：本轮无产出。"

# 06：Notepad 指令分隔符——响应含 "记录：{note}" 子串即逐条入 Notepad
_NOTE_MARKER = "记录："


def _parse_notes(text: str) -> list[str]:
    """「记录：{note}」指令解析：str.split(_NOTE_MARKER) 后取非空段，
    段尾空白 strip；无→零条（单层 split——note 内再含分隔符不递归拆分）。"""
    return [segment.strip() for segment in text.split(_NOTE_MARKER)[1:] if segment.strip()]


# 07 票："写入：{文件名}\n{多行内容}" 指令分隔符（行首模式）
_WRITE_MARKER = "\n写入："


def _parse_writes(text: str) -> list[tuple[str, str]]:
    """「写入：{文件名}\\n{内容}」解析：按 "\\n写入：" 分段（前导补 \\n——
    响应以"写入："开头即首行行首），每段首行=文件名，其后为内容到段尾
    （strip 尾空白）；无→零条。

    行首模式：行中粘连（"先写入：…"）不误中；文件名为空或段内无换行的段不产条目。
    """
    results: list[tuple[str, str]] = []
    for segment in ("\n" + text).split(_WRITE_MARKER)[1:]:
        first_break = segment.find("\n")
        if first_break < 0:
            continue  # 段内无换行：无内容体，不产条目
        filename = segment[:first_break].strip()
        content = segment[first_break + 1 :].rstrip()
        if not filename:
            continue
        results.append((filename, content))
    return results


def _apply_writes(
    shared_docs: Any, way: str, text: str
) -> list[str]:
    """grilling 身体交付物落盘：解析"写入："指令 → 白名单落盘。

    返回被拒文件名列表（不在 DELIVERABLE_SETS[way] 白名单→跳过），
    调用方记 round_end 提示。way1 不调用本函数（不解析写入）。
    """
    rejected: list[str] = []
    for filename, content in _parse_writes(text):
        if not shared_docs.write_deliverable(filename, content, way=way):
            rejected.append(filename)
    return rejected


def _way1_actor_body(state: Mapping[str, Any], config: Any, model: Any) -> str:
    """way1 身体：ReAct 对话推进（05 骨架形态：单次 complete 出牌）。"""
    messages = _actor_model_messages(state)
    result = model.complete(
        messages,
        role=Role.ACTOR.value,
        thread_id=_thread_id_from(config),
    )
    return str(result.text)


# 07 终裁 B：grilling prompt 差异行——与 way1 身体唯一差异。
_GRILLING_SUFFIX = (
    "\n请先提出一个澄清问题以推进构建（如已完成请输出：完成：{首个未清 todo 的 content}）。"
)


def _grilling_model_messages(state: Mapping[str, Any]) -> list[dict[str, str]]:
    """grilling 身体的消息形态：system 末尾追加澄清行（隔离红线照旧）。"""
    messages = _actor_model_messages(state)
    if messages:
        messages[0]["content"] = str(messages[0]["content"]) + _GRILLING_SUFFIX
    return messages


def _grilling_body(
    state: Mapping[str, Any],
    config: Any,
    model: Any,
    shared_docs: Optional[SharedDocs] = None,
) -> str:
    """way2-4 身体（07 终裁 B）：与 way1 同构的最小 grilling 驱动。

    差异仅在 prompt 末尾追加一行澄清指令；模型响应照旧走 todos 勾选/
    "记录："桥/【R#】落盘/round_summary 全套（由 actor_node 公共工序承担）。

    way4 框架先行（终裁 C）：首轮（state round_count 未设 → 本轮即 1）且
    shared_docs 非 None → 先为 DELIVERABLE_SETS["way4"] 每份文档写占位框架
    （f"# {stem}\\n\\n（待填）\\n"），文件已存在则跳过（幂等），再走模型调用。
    """
    if (
        state.get("build_way") == "way4"
        and shared_docs is not None
        and not int(state.get("round_count") or 0)  # 首轮：round_count 未设/0
    ):
        _lay_scaffold(shared_docs)
    messages = _grilling_model_messages(state)
    result = model.complete(
        messages,
        role=Role.ACTOR.value,
        thread_id=_thread_id_from(config),
    )
    return str(result.text)


def _lay_scaffold(shared_docs: SharedDocs) -> None:
    """占位框架落盘：每份 way4 交付物 f"# {stem}\\n\\n（待填）\\n"；已存在跳过。"""
    from pathlib import Path as _Path

    from project_agent.deliverables import DELIVERABLE_SETS

    for name in DELIVERABLE_SETS["way4"]:
        target = shared_docs.root / name
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        stem = _Path(name).stem
        target.write_text(f"# {stem}\n\n（待填）\n", encoding="utf-8")


def distill_round(messages: Any) -> str:
    """提炼函数（05 票终裁 8，Q53=b）：最后一条 AIMessage 的 content 前 120 字符。

    无 AIMessage → ""。纯函数独立单测；actor 末尾显式调用写 round_summary。
    """
    for msg in reversed(list(messages or [])):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content[:120]
    return ""


# 身体表按派生 build_way 选择（终裁 7）；07 终裁 B：way2-4 映射 grilling 身体。
_ACTOR_BODIES: dict[str, Any] = {
    "way1": _way1_actor_body,
    "way2": _grilling_body,
    "way3": _grilling_body,
    "way4": _grilling_body,
}


def make_actor_node(model: Any = None, shared_docs: Optional[SharedDocs] = None):
    """actor 节点工厂（05 票终裁 7；06 票扩 shared_docs）。

    - 每轮派生 cfg=derive_actor_config(build_way, guidance_mode)——仅用于
      身体选择 `_ACTOR_BODIES.get(way, way1 身体)`，不持久化不写 state
    - model=None：写 round_end(05 骨架通告) 即返，不调模型不产 AIMessage
      （CLI 无真模型时主环 inert 不挂死；真模型票接入后闭合 verifier 环）
      ——即便传 shared_docs 亦然（有模型才有落盘）
    - 有模型：system=assembled_context["system"] + actor_messages 历史转 dict
      调 model.complete(role=actor)；产出 AIMessage 追加 actor_messages；
      todos 按"完成：{content}"精确子串勾选；round_output=模型全文
    - 06（有 shared_docs 且有模型，产 AIMessage 后）：
      ① round_count=(state round_count or 0)+1 写仪表盘
      ② shared_docs.append_round_entry(round_count, 模型全文)——每轮生成物
        带【R#】（BUILD_LOG 连续编号溯源：重规划后继续累加）
      ③ 响应含 "记录：{note}" 子串→逐条 notepad_add +
        notes_version=旧+写入条数（单调自增）
      ④ round_summary/turn_end 照旧（round_end 板用勾选后 todos）
    - shared_docs=None 或 model=None：行为与 05 完全一致（不落盘——既有
      421 测试零改动，硬约束）
    """

    def actor_node(
        state: Mapping[str, Any], config: Optional[Mapping[str, Any]] = None
    ) -> dict[str, Any]:
        if model is None:
            return _round_end(_ACTOR_SKELETON_NOTICE, state)

        cfg = derive_actor_config(state.get("build_way"), state.get("guidance_mode"))
        body = _ACTOR_BODIES.get(cfg["build_way"], _way1_actor_body)
        if body is _grilling_body:
            # 07 终裁 B：grilling 身体吃 shared_docs（way4 首轮框架先行落盘）
            text = body(state, config, model, shared_docs)
        else:
            text = body(state, config, model)
        new_todos = _check_todos(state.get("todos") or [], text)
        ai_message = AIMessage(content=text)
        # Q53=b：节点函数末尾、返回前显式调用提炼函数写 round_summary
        round_summary = distill_round(
            [*(state.get("actor_messages") or []), ai_message]
        )
        updates: dict[str, Any] = {
            "actor_messages": [ai_message],
            "todos": new_todos,
            "round_summary": round_summary,
        }
        if shared_docs is not None:
            # ① 每产出一轮 +1（首个工作轮=【R1】；跨 invoke 持续靠 checkpointer）
            round_count = int(state.get("round_count") or 0) + 1
            # ② 每轮生成物落盘带【R#】
            shared_docs.append_round_entry(round_count, text)
            updates["round_count"] = round_count
            # ③ Notepad 指令解析：逐条入 Notepad + notes_version 单调自增
            notes = _parse_notes(text)
            for note in notes:
                shared_docs.notepad_add(round_count, note)
            updates["notes_version"] = int(state.get("notes_version") or 0) + len(notes)
            # 07：交付物落盘（way2-4 解析"写入："；way1 不解析）
            rejected_writes: list[str] = []
            if cfg["build_way"] != "way1":
                rejected_writes = _apply_writes(shared_docs, cfg["build_way"], text)
        else:
            rejected_writes = []
        # ④ round_end 板用勾选后 todos（05 既有）
        round_text = text
        if rejected_writes:
            round_text = f"{text}\n（提示：{','.join(rejected_writes)} 不在交付物白名单，已跳过落盘）"
        updates.update(_round_end(round_text, {**state, "todos": new_todos}))
        return updates

    return actor_node


_TASK_COMPLETE_RE = re.compile(r"task_complete:\s*(true|false)", re.IGNORECASE)


def _latest_ai_text(state: Mapping[str, Any]) -> str:
    for msg in reversed(list(state.get("actor_messages") or [])):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content
    return ""


def make_verifier_node(model: Any = None):
    """verifier 节点工厂（05 票终裁 4）。

    - 纯代码：todos_all_completed 扫描（空表→False 防御）写入
    - LLM：prompt=任务简报+todo 三态板+最后一条 AIMessage 全文，要求输出
      一行 "task_complete: true/false"；role=verifier；解析 re.search
      匹配 true→True，其余/无匹配→False（fail-closed）
    - 写 task_complete + is_docs_finished（05：全方式=task_complete，
      way2-4 docs 语义 06/07 接管）
    - 计数自增：todos_all_completed and not task_complete → main_loop_count+1
      （节点写，条件边 _after_verifier 纯读）
    - model=None：task_complete=False（fail-closed）+扫描照常+计数照常
      （单元测试用；图内不可达——model=None 时 actor→END 直连跳过 verifier）
    """

    def verifier_node(
        state: Mapping[str, Any], config: Optional[Mapping[str, Any]] = None
    ) -> dict[str, Any]:
        todos = state.get("todos") or []
        todos_all_completed = _todos_all_completed(todos)

        if model is None:
            task_complete = False
        else:
            prompt = (
                f"任务简报：{state.get('task_brief') or ''}\n"
                f"todo 三态板：\n" + "\n".join(_todo_board(state))
                + ("\n" if _todo_board(state) else "")
                + f"最后一条 AI 回复：{_latest_ai_text(state)}\n"
                "请判断任务是否完成。输出一行：task_complete: true 或 task_complete: false"
            )
            result = model.complete(
                [{"role": "user", "content": prompt}],
                role=Role.VERIFIER.value,
                thread_id=_thread_id_from(config),
            )
            match = _TASK_COMPLETE_RE.search(str(result.text))
            task_complete = bool(match and match.group(1).lower() == "true")

        updates: dict[str, Any] = {
            "todos_all_completed": todos_all_completed,
            "task_complete": task_complete,
            "is_docs_finished": task_complete,  # 05：全方式=task_complete
        }
        if todos_all_completed and not task_complete:
            updates["main_loop_count"] = int(state.get("main_loop_count") or 0) + 1
        return updates

    return verifier_node


def loop_exhausted_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """LOOP_EXHAUSTED 节点（05 票终裁 9）：耗尽断点——现场 + 求助说明。"""
    todos = state.get("todos") or []
    done = sum(
        1
        for item in todos
        if isinstance(item, dict) and item.get("status") == "completed"
    )
    count = int(state.get("main_loop_count") or 0)
    payload = validate_payload(
        TurnEndReason.LOOP_EXHAUSTED,
        {
            "scene": f"主环计数 {count}；todos {done}/{len(todos)} 完成",
            "help_text": "已连续 5 轮未通过验收，请人工接管：调整任务简报或直接指示下一步。",
        },
    )
    return {
        "turn_end_reason": TurnEndReason.LOOP_EXHAUSTED.value,
        "turn_end_payload": payload,
    }
