"""骨架节点：ask_tasks / build_ways（choice:build_way 断点流）/ guidance_trigger / planner。

全部可重入：已写字段不再改写（断点续跑下轮重进不重复副作用）。
build_ways 由 make_build_ways_node(model) 工厂构造——model=None 走静态推荐。
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Mapping, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

# 节点 config 注解钉 typing.Optional 形式（非 PEP 604 `| None`）：langgraph
# 1.2.17 的签名白名单只认 Optional[RunnableConfig]（含字符串注解形式），
# 写 `RunnableConfig | None` 会触发 UserWarning 且 config 不再注入。
from project_agent.ask_agent import build_guidance
from project_agent.compression import (
    DEFAULT_BUDGET_TOKENS,
    CompactionPack,
    compress_rounds,
    find_error_conjectures,
    format_head_pack,
    parse_head_pack,
    plan_packs,
    round_texts,
    should_compress,
)
from project_agent.onboarding import (
    interpret_answer,
    next_unset_field,
    question_for,
)
from project_agent.protocol import Role, TurnEndReason, validate_payload
from project_agent.routing import _todos_all_completed, derive_actor_config
from project_agent.scopes import rule_for, tools_for_scope
from project_agent.shared_docs import SharedDocs, align_guidance_read, guidance_gate
from project_agent.skills import recommendation_reason, skill_heads
from project_agent.tools.registry import ALL_TOOLS

# 已注册技能名集合（触发判定的命中表）
_SKILL_NAMES = frozenset(head.name for head in skill_heads())


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
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
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
            payload = _reuse_payload(state, TurnEndReason.CHOICE_BUILD_WAY)
            if payload is not None and _recommended_from_payload(payload) is None:
                payload = None  # recommendation 不可解释 → 退静态推荐
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

    def proposals_node(
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
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
            payload = _reuse_payload(state, TurnEndReason.CHOICE_PROPOSAL)
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
    - 07 终裁 D（验收 5）：way4 且 selected_proposal 已设 → 首项改为
      f"深化方案：{proposal_set[idx]}"（超过 40 字截断），其余项照 way4 模板；
      其余方式照旧模板
    """
    way = str(state.get("build_way") or "")
    contents = list(_PLANNER_TEMPLATES.get(way, [])) or [_PLANNER_FALLBACK]
    if way == "way4" and state.get("selected_proposal") is not None:
        proposal_set = [str(item) for item in (state.get("proposal_set") or [])]
        idx = state.get("selected_proposal")
        if isinstance(idx, int) and 0 <= idx < len(proposal_set):
            summary = proposal_set[idx][:40]
            contents = [f"深化方案：{summary}", *contents[1:]]
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


def make_assembler_node(
    shared_docs: Optional[SharedDocs] = None,
):
    """context_assembler 节点工厂（05 终裁 6 → 09 工厂化+升级；07 织入脚手架提示）。

    写 assembled_context（每轮整覆写，state key 无 reducer）；不写任何消息。
    09 组装五段：
    - system = base + "\\n" + 作用域规则行 + "\\n" + todo 板渲染 + "\\n"
      + notepad 切片块 + "\\n" + 技能头块
    - 新键 tools_subset = sorted(tools_for_scope(current_scope, 全矩阵))
      （scope 交集——"送"半段的消费材料）
    - 新键 skills = [name：one_liner]（技能头，懒加载——只有名字+一句话）
    - shared_docs 非 None 时读 notepad 切片（验收 6）：guidance_gate(
      notes_version, guidance_read_version) 真 → 追加【Notepad】块（全部
      条目行【R#】- content）+ 写 guidance_read_version 对齐（节点写，下轮
      差=0 不再注入——stale-read 杜绝）；门假 → 零块零写。
    - shared_docs=None → 零 Notepad 块零版本写（既有行为零回归）。
    07 终裁 C（DocScaffold）：shared_docs 非 None 且 build_way=="way4" 且
    工作区无交付物框架（首个文档不存在）→ system 末尾追加框架先行说明行；
    框架已存在则不追加（首轮落框架后自然消失）。
    """

    def context_assembler_node(
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
    ) -> dict[str, Any]:
        todos = state.get("todos") or []
        current_scope = str(state.get("current_scope") or "main")

        # —— 装（五段 system 组装）——
        base = (
            f"你是构建 agent。当前方式 {state.get('build_way') or ''}，"
            f"指引 {state.get('guidance_mode') or ''}，"
            f"待办 {_pending_count(todos)} 项"
        )
        scope_line = f"【作用域】{rule_for(current_scope)}"
        board_lines = list(_todo_board(state))
        sections = [base, scope_line, "\n".join(board_lines)]

        updates: dict[str, Any] = {}

        # notepad 切片块（版本门，验收 6）——assembler 无句柄时零块零写
        if shared_docs is not None:
            notes_version = int(state.get("notes_version") or 0)
            guidance_read_version = int(state.get("guidance_read_version") or 0)
            if guidance_gate(notes_version, guidance_read_version):
                entries = shared_docs.notepad_entries()
                if entries:
                    sections.append("【Notepad】\n" + "\n".join(
                        f"【R{no}】- {content}" for no, content in entries
                    ))
                # 节点写对齐：下轮差=0 不再注入（stale-read 杜绝）
                updates["guidance_read_version"] = align_guidance_read(notes_version)

        # 技能头块：只注名字+一句话（懒加载——全文触发时才读入）
        skill_lines = [f"{h.name}：{h.one_liner}" for h in skill_heads()]
        sections.append("【技能】\n" + "\n".join(skill_lines))

        # 07：way4 DocScaffold 框架先行说明（无框架时才追加）
        if (
            state.get("build_way") == "way4"
            and shared_docs is not None
            and not _scaffold_exists(shared_docs)
        ):
            sections.append(_SCAFFOLD_HINT.strip())

        updates["assembled_context"] = {
            "system": "\n".join(sections),
            "todo_board": board_lines,
            "scope": current_scope,
            "tools_subset": sorted(
                tools_for_scope(current_scope, frozenset(ALL_TOOLS))
            ),
            "skills": skill_lines,
        }
        return updates

    return context_assembler_node


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
    """隔离红线（验收 7）：messages 只含 system + actor 私有历史——绝不掺其他角色历史。

    09 工具子集送达：system 尾行注入 "【可用工具】a、b、c"（子集=assembler
    装的 scope 交集——终裁：不用 langchain middleware，1.x 版本敏感，改在
    actor 的 model 调用前注入 system 尾行）。
    """
    context = state.get("assembled_context") or {}
    system = str(context.get("system") or "")
    tools_subset = [str(tool) for tool in context.get("tools_subset") or ()]
    if tools_subset:
        system += f"\n【可用工具】{'、'.join(tools_subset)}"
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
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

# 09：技能懒加载触发/推荐理由模式（"送"半段轻桩）
_SKILL_MARKER = "技能："
_RECOMMEND_RE = re.compile(r"推荐技能：([^\n（(]+)[（(]([^）)]*)[）)]")


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


def _triggered_skill(text: str) -> str | None:
    """技能懒加载触发：响应含 "技能：{name}" 子串 → name（首个空白分词）
    命中已注册技能头 → 返回 name（skill_body 全文读出即触发——不进模型
    调用）；无命中→None。"""
    for segment in text.split(_SKILL_MARKER)[1:]:
        tokens = segment.strip().split()
        if tokens and tokens[0] in _SKILL_NAMES:
            return tokens[0]
    return None


def _apply_recommendation_reason(text: str) -> str:
    """推荐理由 ≤20 字代码硬约束：响应含 "推荐技能：{name}（{reason}）" 模式
    → reason 过 recommendation_reason 截断（与 02 build_ways 同法）。"""
    def _clip(match: re.Match[str]) -> str:
        return f"推荐技能：{match.group(1)}（{recommendation_reason(match.group(2))}）"

    return _RECOMMEND_RE.sub(_clip, text)


def _delivery_output(text: str, shared_docs: Any) -> str:
    """actor 送达后置：技能懒加载触发提示（shared_docs 可用才记；语义桩——
    skill_body(name) 读出即触发，不进模型调用）。推荐理由截断与之独立叠加。"""
    out = _apply_recommendation_reason(text)
    if shared_docs is not None:
        name = _triggered_skill(text)
        if name is not None:
            out += f"（技能 {name} 已全文载入）"
    return out


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
    - 09 送达扩展：round_output 过 _delivery_output——推荐理由模式截断
      （≤20 字硬约束）+ shared_docs 可用且技能命中时记 round_end 提示
      "技能 {name} 已全文载入"（懒加载触发桩；AIMessage/落盘/round_summary
      均保持模型原文——提示只进断点 payload）
    - shared_docs=None 或 model=None：行为与 05 完全一致（不落盘——既有
      421 测试零改动，硬约束）
    """

    def actor_node(
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
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
        # ④ round_end 板用勾选后 todos（05 既有）；round_output 过 09 送达
        # 后置（推荐理由截断 + 技能懒加载触发提示）+ 07 白名单拒绝提示
        round_text = _delivery_output(text, shared_docs)
        if rejected_writes:
            round_text = f"{round_text}\n（提示：{','.join(rejected_writes)} 不在交付物白名单，已跳过落盘）"
        # 10：图内新手指引后置工序——版本门（差>0）+ 材料包单发；
        # 指引文本只进 round_output 尾部，节点写 guidance_read_version 对齐。
        guidance_mode = state.get("guidance_mode")
        if shared_docs is not None and guidance_mode in ("auto", "ask"):
            notes_version = int(updates.get("notes_version") or 0)
            if guidance_gate(
                notes_version, int(state.get("guidance_read_version") or 0)
            ):
                latest_round = int(updates.get("round_count") or 0)
                guidance_text = build_guidance(
                    model,
                    round_summary=round_summary,
                    notes=shared_docs.notepad_entries(),
                    doc_slice=shared_docs.read_round(latest_round) or "",
                    thread_id=_thread_id_from(config),
                )
                prefix = "[指引询问] " if guidance_mode == "ask" else ""
                round_text = f"{round_text}\n{prefix}{guidance_text}"
                updates["guidance_read_version"] = align_guidance_read(notes_version)
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
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
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


# —— 11 票：docs_done 断点（demo 决议）+ DemoAgent（生成不运行）——

_DOCS_DONE_OPTIONS: list[str] = ["构建 demo", "跳过"]
# 决议解释关键词（序：跳过先于构建——"不"优先）
_DOCS_SKIP_KEYWORDS = ("跳过", "不")
_DOCS_BUILD_KEYWORDS = ("构建", "demo")


def _deliverables_overview(state: Mapping[str, Any]) -> str:
    """交付概览行："交付物集 N 份已就绪（文件名, …）"（未知 way → 0 份防御）。"""
    from project_agent.deliverables import DELIVERABLE_SETS

    names = list(DELIVERABLE_SETS.get(str(state.get("build_way") or ""), ()))
    return f"交付物集 {len(names)} 份已就绪（{', '.join(names)}）"


def _docs_done_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(
        TurnEndReason.DOCS_DONE,
        {
            "deliverables_overview": _deliverables_overview(state),
            "options": list(_DOCS_DONE_OPTIONS),
        },
    )


def _reuse_payload(
    state: Mapping[str, Any], reason: TurnEndReason
) -> dict[str, Any] | None:
    """复用上轮 turn_end_payload（校验通过才复用；重发断点零副作用）。

    三处决议节点共用（choice:build_way / choice:proposal / docs_done）：
    不可解释输入 → 复用上轮已验证 payload 重发，零 model 调用（可重入）。
    """
    last_payload = state.get("turn_end_payload")
    if not isinstance(last_payload, Mapping):
        return None
    try:
        return validate_payload(reason, dict(last_payload))
    except Exception:
        return None


def docs_done_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """docs_done 断点节点（11 票终裁 A，纯代码零 LLM）。

    - demo_phase 已决（building/skipped）→ {}（可重入幂等零副作用）
    - resolution_inputs 非空 → 解释自由文本：
      "跳过"/"不"/"2" → demo_phase="skipped" + round_end("已跳过 demo")；
      "构建"/"demo"/"1" → demo_phase="building"（**不含 turn_end**——同轮接
      DEMO_AGENT，断点由后节点写）；无匹配 → 清通道 + 复用上轮 payload 重发
      （不可复用则按当前 way 重建）——零副作用
    - 无 pending → 发 docs_done 断点：交付概览 + ["构建 demo", "跳过"]
    """
    if state.get("demo_phase"):
        return {}

    pending = state.get("resolution_inputs") or []
    if pending:
        text = str(pending[-1])
        lowered = text.lower()
        if any(keyword in text for keyword in _DOCS_SKIP_KEYWORDS) or text.strip() == "2":
            return {
                "demo_phase": "skipped",
                "resolution_inputs": [],
                **_round_end("已跳过 demo", state),
            }
        if (
            any(keyword in lowered for keyword in _DOCS_BUILD_KEYWORDS)
            or text.strip() == "1"
        ):
            return {"demo_phase": "building", "resolution_inputs": []}
        payload = _reuse_payload(state, TurnEndReason.DOCS_DONE) or _docs_done_payload(state)
        return {
            "resolution_inputs": [],
            "turn_end_reason": TurnEndReason.DOCS_DONE.value,
            "turn_end_payload": payload,
        }

    return {
        "turn_end_reason": TurnEndReason.DOCS_DONE.value,
        "turn_end_payload": _docs_done_payload(state),
    }


_DEMO_TASK_LINE = "任务：为已完成的交付物生成可运行 demo 与运行指南。"
# 响应内运行指令行首模式："运行：{cmd}"（行中粘连不误中）
_DEMO_RUN_RE = re.compile(r"^[ \t]*运行[:：][ \t]*(.+)$", re.MULTILINE)
_DEMO_RUN_PROMPT = "运行权在用户（ADR-0003）：请自行执行 {cmd}"
_DEMO_SKELETON_NOTICE = "demo 轮待真模型接入（11 骨架）：本轮无产出。"


def _demo_model_messages(state: Mapping[str, Any]) -> list[dict[str, str]]:
    """隔离红线照旧：任务行 + demo 私有历史转 dict——绝不掺其他角色历史。"""
    task_line = (
        f"{_DEMO_TASK_LINE}\n交付物：{_deliverables_overview(state)}"
        f"\n报错上下文：{_demo_tail(state)}"
    )
    messages: list[dict[str, str]] = [{"role": "user", "content": task_line}]
    for msg in state.get("demo_messages") or []:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": str(msg.content)})
    return messages


def _demo_tail(state: Mapping[str, Any]) -> str:
    """报错上下文 = demo_messages 尾部（最后一条非空文本）；无 → "无"。"""
    for msg in reversed(list(state.get("demo_messages") or [])):
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return "无"


def _parse_run_commands(text: str) -> list[str]:
    """「运行：{cmd}」指令解析（行首模式）：返回命令列表；无→[]。"""
    return [
        match.group(1).strip()
        for match in _DEMO_RUN_RE.finditer(text)
        if match.group(1).strip()
    ]


def make_demo_agent_node(
    model: Any = None, shared_docs: Optional[SharedDocs] = None
):
    """DemoAgent 节点工厂（11 票终裁 B；ADR-0003 生成不运行）。

    - model=None：写 round_end(骨架通告) 即返（不调模型不产 AIMessage）
    - 有模型：messages=[任务行（交付概览+报错上下文）] + demo_messages 历史转
      dict；model.complete(role="demo_agent")
    - 产出 AIMessage 追加 demo_messages；响应含 "写入：{文件名}\\n{内容}" →
      shared_docs.write_any 落盘（无白名单）；turn_end=round（round_output=
      摘要 distill_round）
    - 响应含 "运行：{cmd}" → round_output 追加"运行权在用户（ADR-0003）：
      请自行执行 {cmd}"——**绝不调用 ShellTool**（运行权留人手）
    - 报错修复：demo_messages 尾部报错文本进任务行"报错上下文"，每轮一个
      修复循环（计数 REPL 融合时自增，条件边 _after_demo 读）
    """

    def demo_agent_node(
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
    ) -> dict[str, Any]:
        if model is None:
            return _round_end(_DEMO_SKELETON_NOTICE, state)

        messages = _demo_model_messages(state)
        result = model.complete(
            messages,
            role=Role.DEMO_AGENT.value,
            thread_id=_thread_id_from(config),
        )
        text = str(result.text)
        ai_message = AIMessage(content=text)
        if shared_docs is not None:
            for filename, content in _parse_writes(text):
                shared_docs.write_any(filename, content)

        summary = distill_round(
            [*(state.get("demo_messages") or []), ai_message]
        )
        run_prompts = [
            _DEMO_RUN_PROMPT.format(cmd=cmd) for cmd in _parse_run_commands(text)
        ]
        round_text = "\n".join([summary, *run_prompts]) if run_prompts else summary
        return {
            "demo_messages": [ai_message],
            **_round_end(round_text, state),
        }

    return demo_agent_node


# —— 12 票：finalizer 收尾整理 + check_proper_output 终检管线 ——


_FINAL_REPORT_PROMPT_HEAD = "任务：{brief}\n方式：{way}\n最后轮摘要：{round_summary}\n"
_NOTEPAD_HEADLINE = "Notepad 要点："


def _notepad_headlines(shared_docs: Any, limit: int = 5) -> str:
    """NOTES.md 概览：前 {limit} 条（content），无→"无"。"""
    if shared_docs is None:
        return "无"
    entries = shared_docs.notepad_entries()
    if not entries:
        return "无"
    return "\n".join(f"- {content}" for _no, content in entries[:limit])


def make_finalizer_node(
    model: Any = None,
    store: Any = None,
    shared_docs: Optional[SharedDocs] = None,
):
    """finalizer 节点工厂（12 票）：收尾整理产 final_report。

    - prompt 汇总会话四要素：任务简报/构建方式/最后轮摘要/NOTES 概览
      （前 5 条封顶），要求产出 final_report（项目成果+经验教训，200 字内）
    - role="finalizer"；产出 final_report 写 state
    - store 非 None → 存 f"final_report:{task_brief}"（跨线程长期记忆，
      新会话 ask_tasks 检索注入——langgraph Store 正式接入留接线票）
    - turn_end=round（round_output=报告全文；CHECK_PROPER_OUTPUT 后续
      同轮接管终态——finished 断点由 check 节点写）
    - model=None：写 round_end(骨架通告) 即返（CLI 无真模型不挂死）
    """

    def finalizer_node(
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
    ) -> dict[str, Any]:
        if model is None:
            return _round_end("finalizer 待真模型接入（12 骨架）：本轮无产出。", state)

        prompt = (
            _FINAL_REPORT_PROMPT_HEAD.format(
                brief=state.get("task_brief") or "",
                way=state.get("build_way") or "",
                round_summary=state.get("round_summary") or "",
            )
            + _NOTEPAD_HEADLINE
            + _notepad_headlines(shared_docs)
            + "\n产出一份 final_report（项目成果+经验教训，200 字内）"
        )
        result = model.complete(
            [{"role": "user", "content": prompt}],
            role=Role.FINALIZER.value,
            thread_id=_thread_id_from(config),
        )
        report = str(result.text)
        updates: dict[str, Any] = {
            "final_report": report,
            **_round_end(report, state),
        }
        if store is not None:
            # key=task_brief 原文（简化终裁；langgraph Store 正式接入留接线票）
            store.put(f"final_report:{state.get('task_brief') or ''}", report)
        return updates

    return finalizer_node


def make_check_node(
    model: Any = None,
    shared_docs: Optional[SharedDocs] = None,
):
    """check_proper_output 节点工厂（12 票，=Q22 质检管线）。

    - deliverable_set = DELIVERABLE_SETS[build_way]（对账表驱动）
    - run_final_check(root=shared_docs.root, ...)——完整管线（快照/剥离/
      误伤/语义/畸形/双份交付）
    - output_clean 真 → turn_end_reason=finished + validate_payload(
      FINISHED, {"delivery_paths": 结果 delivery_paths}) + output_clean=True
    - 假 → final_check_loop_count=旧+1；==5 → LOOP_EXHAUSTED 断点（scene
      含"终检环计数 5"与失败明细）；<5 → 回 planner 开新环：todos 重置为
      [{"content": "系统性修复：{失败明细首项}", "status": "pending"}] +
      turn_end=round（"终检未过：{失败摘要}，已开新环修复"）
    - shared_docs=None：终检无从落盘 → 骨架通告（round 断点，CLI 零回归）
    """

    def _failure_detail(result: Mapping[str, Any]) -> str:
        """失败明细首项：missing/误伤/语义/畸形 按序拼接摘要。"""
        parts: list[str] = []
        for key, label in (
            ("missing", "缺件"),
            ("false_positives", "误伤"),
            ("semantic_failures", "语义"),
            ("malformed", "畸形"),
        ):
            items = [str(x) for x in result.get(key) or []]
            if items:
                parts.append(f"{label}:{','.join(items)}")
        return "；".join(parts)

    def check_node(
        state: Mapping[str, Any], config: Optional[RunnableConfig] = None
    ) -> dict[str, Any]:
        if shared_docs is None or model is None:
            return _round_end("终检待接线（需 shared_docs+model）：本轮无产出。", state)

        from project_agent.deliverables import DELIVERABLE_SETS
        from project_agent.final_check import run_final_check

        deliverable_set = DELIVERABLE_SETS.get(str(state.get("build_way") or ""), ())
        result = run_final_check(
            root=shared_docs.root,
            deliverable_set=deliverable_set,
            model=model,
            thread_id=_thread_id_from(config),
        )

        if result["output_clean"]:
            payload = validate_payload(
                TurnEndReason.FINISHED,
                {"delivery_paths": result["delivery_paths"]},
            )
            return {
                "output_clean": True,
                "turn_end_reason": TurnEndReason.FINISHED.value,
                "turn_end_payload": payload,
            }

        # 未过：终检环计数 +1
        loop_count = int(state.get("final_check_loop_count") or 0) + 1
        detail = _failure_detail(result)
        if loop_count >= 5:
            payload = validate_payload(
                TurnEndReason.LOOP_EXHAUSTED,
                {
                    "scene": f"终检环计数 5；失败明细：{detail}",
                    "help_text": "终检连续 5 轮未通过，请人工接管：核对交付物或调整任务简报。",
                },
            )
            return {
                "final_check_loop_count": loop_count,
                "turn_end_reason": TurnEndReason.LOOP_EXHAUSTED.value,
                "turn_end_payload": payload,
            }

        # <5：回 planner 开新环——todos 已设（planner 见 todos 已设重规划保计数）
        return {
            "final_check_loop_count": loop_count,
            "todos": [
                {
                    "content": f"系统性修复：{detail or '终检未过'}",
                    "status": "pending",
                }
            ],
            **_round_end(f"终检未过：{detail}，已开新环修复", state),
        }

    return check_node


def loop_exhausted_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """LOOP_EXHAUSTED 节点（05 票终裁 9）：耗尽断点——现场 + 求助说明。

    12：终检环计数入 scene（终检耗尽路径可见）；可重入——上轮已写
    loop_exhausted 断点（check 节点 5 计时含失败明细版）则零改写保留。
    """
    if state.get("turn_end_reason") == TurnEndReason.LOOP_EXHAUSTED.value:
        return {}  # 已写耗尽断点（12 check 版含失败明细）——保留不覆盖
    todos = state.get("todos") or []
    done = sum(
        1
        for item in todos
        if isinstance(item, dict) and item.get("status") == "completed"
    )
    count = int(state.get("main_loop_count") or 0)
    demo_count = int(state.get("demo_loop_count") or 0)
    final_check_count = int(state.get("final_check_loop_count") or 0)
    payload = validate_payload(
        TurnEndReason.LOOP_EXHAUSTED,
        {
            "scene": (
                f"主环计数 {count}；demo 环计数 {demo_count}；"
                f"终检环计数 {final_check_count}；"
                f"todos {done}/{len(todos)} 完成"
            ),
            "help_text": "已连续 5 轮未通过验收，请人工接管：调整任务简报或直接指示下一步。",
        },
    )
    return {
        "turn_end_reason": TurnEndReason.LOOP_EXHAUSTED.value,
        "turn_end_payload": payload,
    }


# —— 08 票：统一压缩检查（Q54 挂点核心，纯函数无 state 依赖）——


def _head_pack_from_messages(messages: Any) -> list[tuple[int, int]]:
    """从消息头部单包文本解析既有压缩区间（无头部单包 → ()）。"""
    for msg in messages or []:
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.startswith("【R"):
            ranges = parse_head_pack(content)
            if ranges:
                return ranges
    return []


def _existing_packs_texts(messages: Any) -> list[tuple[int, int, str]]:
    """解析消息里既有的头部单包（区间 + 该段摘要文本），保序返回。"""
    existing: list[tuple[int, int, str]] = []
    for msg in messages or []:
        content = getattr(msg, "content", None)
        if not isinstance(content, str):
            continue
        ranges = parse_head_pack(content)
        if not ranges:
            continue
        # 按包目录切分：每段【R#-R#-compact】行之后的文本到下一目录行
        segments = re.split(r"【R(\d+)-R(\d+)-compact】", content)
        # segments = [前导, s1, e1, text1, s2, e2, text2, ...]
        i = 1
        while i + 2 < len(segments) + 1 and i + 1 < len(segments):
            start, end, text = int(segments[i]), int(segments[i + 1]), segments[i + 2]
            existing.append((start, end, text.strip()))
            i += 3
    return existing


def run_compression_check(
    *,
    messages: Any,
    model: Any,
    cheap_model: Any,
    thread_id: str,
    shared_docs: Optional[SharedDocs] = None,
    notes_version: int = 0,
    manual: bool = False,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> dict[str, Any] | None:
    """统一压缩检查（Q54：模型调用前）——返回 state 更新 dict 或 None。

    流程：should_compress(manual 可绕过) → round_texts → plan_packs（existing
    解析自消息头部单包）→ compress_rounds 每包（便宜模型，role=compressor）
    → 消息重排（Q56 头部单包注入：新 actor_messages = [AIMessage(全部包合并
    文本)] + 保留轮消息）→ conjectures → shared_docs.notepad_add(轮号=end) +
    notes_version 自增。返回 dict 附 compacted_rounds（验收 6 溯源）。

    actor_messages 走 add_messages 追加式 reducer——重排编码：
    - 头部单包 AIMessage 复用消息列表首条消息的 id（replace 语义）
    - 被压轮消息以 RemoveMessage(id=...) 剔除（无 id 的消息按位置补 id）
    model 参数是挂点协议的一部分（Q54 全部 LLM 调用点同一检查）；本函数
    本体不调用主模型——主模型调用仍属各节点身体。
    """
    if cheap_model is None:
        return None
    if not manual and not should_compress(messages, budget_tokens=budget_tokens):
        return None

    rounds = round_texts(messages)
    existing = _head_pack_from_messages(messages)
    packs_plan = plan_packs(rounds, existing=existing, budget_tokens=budget_tokens)
    if not packs_plan:
        return None

    rounds_by_no = dict(rounds)
    new_packs: list[CompactionPack] = []
    conjecture_notes: list[tuple[int, str]] = []
    compacted_rounds: list[tuple[int, int]] = list(existing)
    for start, end in packs_plan:
        pack_rounds = [(no, rounds_by_no[no]) for no in range(start, end + 1)]
        summary = compress_rounds(cheap_model, pack_rounds, thread_id)
        new_packs.append(
            CompactionPack(
                covered_rounds=tuple(range(start, end + 1)), summary=summary
            )
        )
        compacted_rounds.append((start, end))
        for note in find_error_conjectures(summary):
            conjecture_notes.append((end, note))

    # 既有包（摘要文本保留）+ 新包合并为头部单包
    existing_texts = _existing_packs_texts(messages)
    all_packs: list[CompactionPack] = [
        CompactionPack(
            covered_rounds=tuple(range(start, end + 1)), summary=text
        )
        for start, end, text in existing_texts
    ] + new_packs
    head_text = format_head_pack(all_packs)

    # 保留轮：未被压缩的轮（含最近 keep_last 及既有包之外的零散轮）原序保留
    compressed_nos = {no for start, end in compacted_rounds for no in range(start, end + 1)}
    retained: list[Any] = []
    round_no = 0
    for msg in messages or []:
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str) and parse_head_pack(content):
                continue  # 旧头部单包被新头部单包取代
            round_no += 1
            if round_no in compressed_nos:
                continue
            retained.append(msg)
        else:
            retained.append(msg)

    updates: dict[str, Any] = {
        "actor_messages": _rearrange_messages(messages, retained, head_text),
        "compacted_rounds": compacted_rounds,
    }
    if conjecture_notes:
        if shared_docs is not None:
            for round_no_end, note in conjecture_notes:
                shared_docs.notepad_add(round_no_end, note)
        updates["notes_version"] = notes_version + len(conjecture_notes)
    return updates


def _rearrange_messages(
    messages: Any, retained: list[Any], head_text: str
) -> list[Any]:
    """重排编码：add_messages reducer 下的 [头部单包] + 保留轮。

    - 首条消息（任意类型）被头部单包 AIMessage 以同 id 覆写（replace 语义）
    - 其余消息中被压轮（不在 retained）发 RemoveMessage(id) 剔除
    - 无 id 的消息先按位置补 uuid（RemoveMessage 按 id 定位）
    """
    from langchain_core.messages.modifier import RemoveMessage

    msg_list = list(messages or [])
    batch: list[Any] = []
    retained_ids = {id(m) for m in retained}
    first_id = None
    for idx, msg in enumerate(msg_list):
        msg_id = getattr(msg, "id", None)
        if not msg_id:
            msg_id = uuid.uuid4().hex
            try:
                msg.id = msg_id
            except Exception:
                # frozen 消息：换同内容带 id 副本
                msg = msg.__class__(content=msg.content, id=msg_id)
                msg_list[idx] = msg
        if idx == 0:
            first_id = msg_id
            batch.append(AIMessage(content=head_text, id=first_id))
        elif id(msg) not in retained_ids:
            batch.append(RemoveMessage(id=msg_id))
    if not msg_list:  # 无消息（防御）：头部单包直接追加
        batch.append(AIMessage(content=head_text))
    return batch


def with_compression(
    node_fn: Any,
    *,
    cheap_model: Any = None,
    shared_docs: Optional[SharedDocs] = None,
    messages_key: str = "actor_messages",
) -> Any:
    """装饰器工厂（08 票挂接方式终裁）：不改既有节点签名，包装任意节点。

    调前跑 run_compression_check（传 state 的 messages_key 历史 / configurable
    thread_id / shared_docs / notes_version），其更新合并进 state 后再调
    原节点；cheap_model=None → 返回原节点裸函数（467 基线零回归）。

    挂点：actor / verifier / assembler 三节点（planner 无 LLM 调用不挂；
    11 票补第四挂点 DEMO_AGENT，messages_key="demo_messages"——demo 轮同过
    统一压缩检查）。主模型参数经闭包由被包装节点自身持有。
    """

    if cheap_model is None:
        return node_fn

    def wrapped(state: Mapping[str, Any], config: Optional[RunnableConfig] = None) -> dict[str, Any]:
        compression_updates = run_compression_check(
            messages=state.get(messages_key) or [],
            model=None,
            cheap_model=cheap_model,
            thread_id=_thread_id_from(config),
            shared_docs=shared_docs,
            notes_version=int(state.get("notes_version") or 0),
        )
        if compression_updates is not None and messages_key != "actor_messages":
            # 重排批落在被包装节点的私有 key 上（demo 轮：demo_messages）
            compression_updates[messages_key] = compression_updates.pop(
                "actor_messages"
            )
        if compression_updates is not None:
            merged = dict(state)
            merged.update(compression_updates)
            try:
                node_updates = node_fn(merged, config)
            except TypeError:
                node_updates = node_fn(merged)
            combined = dict(compression_updates)
            combined.update(node_updates)
            return combined
        try:
            return node_fn(state, config)
        except TypeError:
            return node_fn(state)

    return wrapped
