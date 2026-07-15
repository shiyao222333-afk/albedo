"""Albedo (Lian Zhen) · 优点分析编排 (A1)

五透镜萃取内容价值，填 merits 8 子能力（内容轴 6 + 形式轴 2）。
2 次 LLM 调用：内容轴 1 次 + 形式轴 1 次；形式轴挂了不影响内容轴。

架构约束（AI 设计决策，非用户指令）：形式轴(A1.4/A1.5) 与 assess 真实性分离——
形式轴不直接给 trust_score 加分；仅 G1 反向桥可在"高包装+未验证"时下调验真分（保守护栏，在 refine 编排层实现）。
本模块只产 merits，不主动改 trust_score / status（那是验真证据链的职责）。

决策（2026-07-10 锁定）：
  - 2 次 LLM：内容轴(core_insight/reusable_steps/differentiation/pitfalls/
    applicable_scenarios/migration_cost) 1 次 + 形式轴(presentation_craft/
    format_reusable) 1 次
  - 降级：哪次挂对应轴留空、报告标注，另一次照常跑
  - 语言跟原文；提示词"只提取不编造"；信息不足该项留空
  - reusable_steps 为 high-level"可照搬步骤"，与 A2 正式编号 SOP 层次不同不撞车
"""
from __future__ import annotations

from .llm import call_llm_json


# ── 空模板（降级时返回）──
_EMPTY_MERITS: dict = {
    "core_insight": "",
    "reusable_steps": [],
    "differentiation": "",
    "pitfalls": [],
    "applicable_scenarios": [],
    "migration_cost": "",
    "presentation_craft": {},
    "format_reusable": {},
}


def _clean_str(value) -> str:
    return str(value).strip() if value is not None else ""


def _clean_list(value) -> list:
    """规整成非空字符串列表。"""
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []
    return [str(v).strip() for v in value if str(v).strip()]


def _content_axis_messages(clean_text: str, context: str) -> list:
    """内容轴提示词：方法价值 / 批判校验 / 适配落地（6 子能力）。"""
    sys_msg = (
        "你是内容价值分析助手。从给定文本中萃取「方法价值、批判校验、适配落地」三方面价值。\n"
        "严格要求：\n"
        "1. 只提取原文已有的信息，绝不编造、绝不凭空补充。\n"
        "2. 若原文信息不足以提取某项，该项留空（字符串留空、列表留空数组），不要硬凑。\n"
        "3. 输出语言与原文保持一致（原文中文→中文，原文英文→英文）。\n"
        "4. reusable_steps 是 high-level「可照搬的操作步骤」，一句话一条，不是正式编号 SOP。"
    )
    user_parts = [f"待分析文本：\n{clean_text}"]
    if context and context.strip():
        user_parts.append(f"补充背景（仅辅助理解）：\n{context.strip()}")
    user_parts.append(
        "请严格只输出如下 JSON，不要任何额外说明：\n"
        "{\n"
        '  "core_insight": "核心洞察——最值得记住的那个认知/方法（1~2句，不是摘要）",\n'
        '  "reusable_steps": ["可照搬步骤1（一句话）", "步骤2", "..."],\n'
        '  "differentiation": "差异化亮点——与他人同类内容相比的独特之处（一段话）",\n'
        '  "pitfalls": ["陷阱/误区/前提缺失1", "..."],\n'
        '  "applicable_scenarios": ["适用场景1", "..."],\n'
        '  "migration_cost": "迁移成本——搬到自己业务需付出什么代价/具备什么前提（一段话）"\n'
        "}"
    )
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def _form_axis_messages(clean_text: str, context: str) -> list:
    """形式轴提示词：表达形式质量 / 格式可复用（2 子能力）。

    护栏：明确告知模型只评「表达形式」，不评「内容真假」、不影响可信度。
    """
    sys_msg = (
        "你是表达形式分析助手。只分析内容的「表达形式质量」和「格式可复用性」。\n"
        "严格要求：\n"
        "1. 只看「怎么讲的」（结构/技巧/节奏/可套用模板），不看「讲得对不对」。\n"
        "2. 表达精彩绝不代表内容可信——本分析结果不参与任何真实性/可信度判断。\n"
        "3. 只提取原文已有的表达特征，绝不编造；信息不足该项留空。\n"
        "4. 输出语言与原文保持一致（原文中文→中文，原文英文→英文）。"
    )
    user_parts = [f"待分析文本：\n{clean_text}"]
    if context and context.strip():
        user_parts.append(f"补充背景（仅辅助理解）：\n{context.strip()}")
    user_parts.append(
        "请严格只输出如下 JSON，不要任何额外说明：\n"
        "{\n"
        '  "presentation_craft": {\n'
        '    "clarity": "清晰度——表达是否清楚、哪里清楚哪里模糊（一段话）",\n'
        '    "structure_pattern": "结构套路——用了什么叙事/论证结构（如问题-方案-案例）",\n'
        '    "learnable_techniques": ["可学/可操作的表达技巧1", "..."],\n'
        '    "pacing": "节奏——信息密度/详略安排评价（一段话）"\n'
        "  },\n"
        '  "format_reusable": {\n'
        '    "template_skeleton": "可套用的结构模板骨架（一段话或骨架描述）",\n'
        '    "reusable_segments": ["可直接搬用的段落/句式1", "..."],\n'
        '    "adaptation_hints": ["搬到别的题材需怎么改1", "..."]\n'
        "  }\n"
        "}"
    )
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def analyze_merits(clean_text: str, context: str = "") -> dict:
    """对净化后文本萃取 8 子能力优点，填 merits dict。

    参数:
        clean_text: 净化(C2)后的纯文本
        context: 可选补充背景（标题/来源），仅辅助 LLM 理解

    返回:
        dict: merits 8 字段（内容轴 6 + 形式轴 2）；任何 LLM 异常都降级为对应轴留空，
              绝不抛出中断流水线。
    """
    text = (clean_text or "").strip()
    merits = {k: (v.copy() if isinstance(v, list) else v) for k, v in _EMPTY_MERITS.items()}
    if not text:
        return merits

    # ── 内容轴（6 子能力，1 次 LLM）──
    try:
        data = call_llm_json(_content_axis_messages(text, context), max_tokens=2048)
        merits["core_insight"] = _clean_str(data.get("core_insight"))
        merits["reusable_steps"] = _clean_list(data.get("reusable_steps"))
        merits["differentiation"] = _clean_str(data.get("differentiation"))
        merits["pitfalls"] = _clean_list(data.get("pitfalls"))
        merits["applicable_scenarios"] = _clean_list(data.get("applicable_scenarios"))
        merits["migration_cost"] = _clean_str(data.get("migration_cost"))
    except Exception:
        # 内容轴降级：6 字段保持空，形式轴照常跑
        pass

    # ── 形式轴（2 子能力，1 次 LLM，独立 try）──
    try:
        data = call_llm_json(_form_axis_messages(text, context), max_tokens=1536)
        pc = data.get("presentation_craft")
        if isinstance(pc, dict):
            merits["presentation_craft"] = {
                "clarity": _clean_str(pc.get("clarity")),
                "structure_pattern": _clean_str(pc.get("structure_pattern")),
                "learnable_techniques": _clean_list(pc.get("learnable_techniques")),
                "pacing": _clean_str(pc.get("pacing")),
            }
        fr = data.get("format_reusable")
        if isinstance(fr, dict):
            merits["format_reusable"] = {
                "template_skeleton": _clean_str(fr.get("template_skeleton")),
                "reusable_segments": _clean_list(fr.get("reusable_segments")),
                "adaptation_hints": _clean_list(fr.get("adaptation_hints")),
            }
    except Exception:
        # 形式轴降级：2 字段保持空，不影响已填好的内容轴
        pass

    return merits
