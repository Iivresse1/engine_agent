"""技能懒加载（09 票 B 段）：技能头注册表 + 触发时全文 + 推荐理由硬约束。

懒加载语义（GLOSSARY『技能懒加载』）：上下文只注入技能名 + 一句话描述，
SKILL.md 全文在被触发时才读入。skill_body 是"触发时全文读入"的语义桩——
返回模拟的 SKILL.md 全文（# 名字标题 + one_liner 展开的约 200 字说明），
未命中返回 None。

recommendation_reason：推荐理由 ≤20 字代码硬约束（与 02 build_ways 的
推荐理由同法——超长即截断 [:20]，代码层而非提示层强制）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillHead:
    """技能头：名字 + 一句话（上下文只注这么多）。"""

    name: str
    one_liner: str


SKILLS: tuple[SkillHead, ...] = (
    SkillHead("grilling", "连珠追问压测计划"),
    SkillHead("tdd", "红绿重构测试先行"),
    SkillHead("to-spec", "把决策沉淀为规格"),
    SkillHead("teach-me", "页面式深度教学：生成可勾选概念的 HTML 教学页"),
)

# 模拟的 SKILL.md 全文（one_liner 展开的约 200 字说明文本）
_SKILL_BODY_TEXT: dict[str, str] = {
    "grilling": (
        "连珠追问压测计划：在计划成形之初不急于动手，把目标、边界、代价与"
        "失败路径逐条摊开，一轮一轮地追问，每一问都要求可回答、可证伪。"
        "追问的对象是计划本身而非提问者——薄弱的假设会在连续追问下最先露出"
        "破绽，含糊的验收标准会在第三问之前被迫写清，被忽略的外部依赖会在"
        "代价核算处现形。压测通过的计划才值得排期执行；压测不过的计划先回炉"
        "重造。宁可多问一轮，不可错投一步；每一轮追问的产出，都是下一版计划"
        "更硬的证据。"
    ),
    "tdd": (
        "红绿重构测试先行：先写一个注定失败的测试（红），再写恰好让它通过的"
        "实现（绿），随后在测试保护下清理结构（重构）。测试是第一份可执行"
        "规格——它强迫你在动手之前想清接口与边界；红 bar 证明测试真的在测"
        "东西，绿 bar 证明实现恰好够用，重构步则让代码在行为不变的前提下"
        "持续变好。小步快走，永远绿灯提交：任何时刻回退都是安全的，任何缺陷"
        "都有一张失败的测试先行指认。"
    ),
    "to-spec": (
        "把决策沉淀为规格：讨论会散，记忆会骗，只有写下的规格不会跑。每个"
        "关键裁定——选型、边界、协议、取舍——当场落成文字：上下文是什么、"
        "选项有哪些、为什么这样裁、代价与例外写在哪。规格让后来者不必重走"
        "你的弯路，让未来的自己不必重信当时的记忆；争议回到纸上对质，而不是"
        "在口头重新发明。决策一旦成文，便成为下一轮讨论的共同事实基础。"
    ),
    "teach-me": (
        "页面式深度教学：生成可勾选概念的 HTML 教学页。把当前轮次的知识点"
        "做成一页自包含的 HTML，而不是塞进对话流里滚屏。页面结构：页首标注"
        "轮次与日期，随后是'为什么这么做'的短引言，主体分小节讲解每一步在"
        "做什么、涉及哪些概念；每个概念配一句话解释与（如适用）一个极小的"
        "代码或命令示例。页尾放'概念清单'——每项带 checkbox，勾选状态存浏览器"
        " localStorage，已掌握的概念下次不重教。全文中文排版，零外链零 JS 依赖"
        "（勾选逻辑内联），生成后由调用方落盘 teach-me/R{n}/index.html。"
    ),
}


def skill_heads() -> tuple[SkillHead, ...]:
    """全部技能头（上下文注入的全部材料：名字+一句话）。"""
    return SKILLS


def skill_body(name: str) -> str | None:
    """触发时全文读入：name 命中 → 模拟 SKILL.md 全文；未命中 → None。"""
    for head in SKILLS:
        if head.name == name:
            return f"# {name}\n\n{_SKILL_BODY_TEXT[name]}\n"
    return None


def recommendation_reason(reason: str) -> str:
    """推荐理由 ≤20 字代码硬约束：超长截断 [:20]。"""
    return reason[:20]
