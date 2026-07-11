"""Albedo (Lian Zhen) · 结构化提炼编排 (A2)

识别内容结构家族，再路由到对应提取器，产结构化输出：
  - sop 型        → 标准 SOP（TubeScribed 格式）填 `sop`
  - 其余型        → 通用大纲（{概述, 章节:[{小标题,要点}]}）填 `outline`
  sop / outline 互斥填充（一份内容只走一条路）。

2 次 LLM 调用：detect_structure_type（识别） + 路由提取器（提取）。
提取器登记 STRUCTURE_EXTRACTORS 注册表，未来新题材插拔即扩（承载"多题材兼容"要求）。

架构护栏：本模块只做"结构提炼"，不评级不判真假（那是 assess 的事）；
不碰 trust_score / status / merits。text_type（输入格式）与 structure_type（内容结构）正交——
入口是字幕还是文章只影响净化/评估策略，不影响这里怎么识别结构。

决策（2026-07-10 锁定）：
  - 结构家族: sop/argument/case_study/comparison/narrative/qa/mixed/unknown
  - ② STRUCTURE_EXTRACTORS 注册表：非 sop 家族登记提取器，未来新题材插拔即扩
  - ③ sop/outline 互斥填充
  - ④ outline 通用结构 {概述, 章节:[{小标题,要点}]}；各 family 经 family 提示让大纲更有意义
  - ⑤ 降级：识别失败→unknown→通用提取器；提取失败→留空 dict + 报告标注（A4 负责标注）
  - ⑥ text_type(输入格式) 与 structure_type(内容结构) 正交
"""
from __future__ import annotations

from .llm import call_llm_json


# ── 已知结构家族（识别结果必须落在此集合，否则归 unknown）──
_KNOWN_STRUCTURE_TYPES = (
    "sop",
    "argument",
    "case_study",
    "comparison",
    "narrative",
    "qa",
    "mixed",
    "unknown",
)

# ── 空模板（降级时返回）──
_EMPTY_SOP = {
    "purpose": "",
    "preconditions": [],
    "steps": [],
    "warnings": [],
    "completion_checklist": [],
}
_EMPTY_OUTLINE = {
    "overview": "",
    "sections": [],
}


# ── 类型萃取辅助 ──
def _clean_str(value) -> str:
    return str(value).strip() if value is not None else ""


def _clean_list(value) -> list:
    """规整成非空字符串列表。"""
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []
    return [str(v).strip() for v in value if str(v).strip()]


def _clean_outline(value) -> dict:
    """规整 outline 通用结构：{overview, sections:[{subtitle, points}]}。"""
    if not isinstance(value, dict):
        return dict(_EMPTY_OUTLINE)
    sections = []
    raw_sections = value.get("sections") or []
    if isinstance(raw_sections, list):
        for sec in raw_sections:
            if not isinstance(sec, dict):
                continue
            subtitle = _clean_str(sec.get("subtitle"))
            points = _clean_list(sec.get("points"))
            if subtitle or points:
                sections.append({"subtitle": subtitle, "points": points})
    return {
        "overview": _clean_str(value.get("overview")),
        "sections": sections,
    }


# ── A2.1 结构类型识别 ──
def _detect_type_messages(clean_text: str, context: str) -> list:
    sys_msg = (
        "你是内容结构分类器。判断给定文本属于哪种内容结构家族。\n"
        "只看「整体怎么组织的」，不评价内容好坏、不判断真假。\n"
        "严格从以下 8 类中选唯一一个：\n"
        "  sop: 操作步骤/教程/流程指南——含可执行的编号步骤\n"
        "  argument: 观点论证——提出主张并用论据支撑\n"
        "  case_study: 案例拆解——背景+做法+结果/复盘\n"
        "  comparison: 对比评测——多个对象多维度比较\n"
        "  narrative: 叙事/经历分享——按时间或情节展开\n"
        "  qa: 问答答疑——问题+解答\n"
        "  mixed: 混合多种结构、主次难分\n"
        "  unknown: 信息过少或无法归类\n"
        "输出语言与原文一致。"
    )
    user_parts = [f"待分类文本：\n{clean_text}"]
    if context and context.strip():
        user_parts.append(f"补充背景（仅辅助判断）：\n{context.strip()}")
    user_parts.append(
        "请严格只输出如下 JSON，不要任何额外说明：\n"
        '{"type": "sop|argument|case_study|comparison|narrative|qa|mixed|unknown"}'
    )
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def detect_structure_type(clean_text: str, context: str = "") -> str:
    """识别内容结构家族（A2.1）。任何失败都降级为 'unknown'。"""
    text = (clean_text or "").strip()
    if not text:
        return "unknown"
    try:
        data = call_llm_json(_detect_type_messages(text, context), max_tokens=256)
        t = (data.get("type") or "").strip().lower()
        return t if t in _KNOWN_STRUCTURE_TYPES else "unknown"
    except Exception:
        return "unknown"


# ── A2.2 SOP 型提取（TubeScribed 标准格式）──
def _sop_messages(clean_text: str, context: str) -> list:
    sys_msg = (
        "你是标准 SOP 提取器（参考 TubeScribed 商业化格式）。从给定操作教程中，"
        "提炼出可直接照做、可直接交给执行系统的标准操作流程。\n"
        "严格要求：\n"
        "1. 只提取原文已有的步骤，绝不编造步骤或细节。\n"
        "2. 步骤按原文出现的执行顺序编号（idx 从 1 开始）。\n"
        "3. 输出语言与原文一致（原文中文→中文，原文英文→英文）。\n"
        "4. 信息不足的项留空数组/空字符串，不要硬凑。"
    )
    user_parts = [f"待提取 SOP 文本：\n{clean_text}"]
    if context and context.strip():
        user_parts.append(f"补充背景（仅辅助理解）：\n{context.strip()}")
    user_parts.append(
        "请严格只输出如下 JSON，不要任何额外说明：\n"
        "{\n"
        '  "purpose": "这个 SOP 要达成的目的（1 句话）",\n'
        '  "preconditions": ["执行前需具备的前提/工具/权限1", "..."],\n'
        '  "steps": [{"idx": 1, "text": "步骤说明（一句话可操作）"}, {"idx": 2, "text": "..."}],\n'
        '  "warnings": ["注意事项/坑/警告1", "..."],\n'
        '  "completion_checklist": ["怎样算做完了的判定标准1", "..."]\n'
        "}"
    )
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def extract_sop(clean_text: str, context: str = "") -> dict:
    """SOP 型提取（A2.2，TubeScribed 标准格式）。失败降级为空 SOP。"""
    text = (clean_text or "").strip()
    if not text:
        return dict(_EMPTY_SOP)
    try:
        data = call_llm_json(_sop_messages(text, context), max_tokens=2048)
        steps = []
        raw_steps = data.get("steps") or []
        if isinstance(raw_steps, list):
            for i, s in enumerate(raw_steps, start=1):
                if isinstance(s, dict):
                    txt = _clean_str(s.get("text"))
                    idx = s.get("idx") or i
                else:
                    txt = _clean_str(s)
                    idx = i
                if txt:
                    steps.append({"idx": int(idx), "text": txt})
        return {
            "purpose": _clean_str(data.get("purpose")),
            "preconditions": _clean_list(data.get("preconditions")),
            "steps": steps,
            "warnings": _clean_list(data.get("warnings")),
            "completion_checklist": _clean_list(data.get("completion_checklist")),
        }
    except Exception:
        return dict(_EMPTY_SOP)


# ── A2.3 非 SOP 型：通用大纲提取器（注册表载体）──
def _family_hint(family: str) -> str:
    """给通用大纲提取器加一句 family 相关的引导，让不同家族的大纲更有意义。"""
    hints = {
        "argument": "按「主张 → 论据 → 结论」组织章节。",
        "case_study": "按「背景 → 做法 → 结果/复盘」组织章节。",
        "comparison": "每个章节对应一个对比维度或对比对象，要点写差异。",
        "narrative": "按时间或情节顺序组织章节。",
        "qa": "每个章节对应一个问题，要点写解答。",
        "mixed": "按最主要的几条线索组织章节。",
    }
    return hints.get(family, "按内容本身的层次组织章节。")


def _outline_messages(clean_text: str, context: str, family: str) -> list:
    hint = _family_hint(family)
    sys_msg = (
        "你是内容大纲提取器。把给定文本提炼成结构化大纲，便于快速掌握全貌并沉淀知识。\n"
        "严格要求：\n"
        "1. 只提取原文已有的信息，绝不编造。\n"
        "2. 输出语言与原文一致（原文中文→中文，原文英文→英文）。\n"
        "3. 信息不足的章节不要硬凑；要点用短语或短句，一句话一条。\n"
        f"4. {hint}"
    )
    user_parts = [f"待提取大纲文本：\n{clean_text}"]
    if context and context.strip():
        user_parts.append(f"补充背景（仅辅助理解）：\n{context.strip()}")
    user_parts.append(
        "请严格只输出如下 JSON，不要任何额外说明：\n"
        "{\n"
        '  "overview": "内容概述（1~2 句）",\n'
        '  "sections": [{"subtitle": "小节标题", "points": ["要点1", "要点2"]}, ...]\n'
        "}"
    )
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def _generic_outline_extractor(clean_text: str, context: str = "", family: str = "") -> dict:
    """通用大纲提取器（A2.3）。所有非 sop 家族 + unknown 回退共用。失败降级为空大纲。"""
    text = (clean_text or "").strip()
    if not text:
        return dict(_EMPTY_OUTLINE)
    try:
        data = call_llm_json(_outline_messages(text, context, family), max_tokens=1536)
        return _clean_outline(data)
    except Exception:
        return dict(_EMPTY_OUTLINE)


# ── A2.3 结构提取器注册表（插拔即扩的物理落点）──
# 非 sop 家族 → 大纲提取器。MVP 全部走通用大纲（family 提示微调），
# 未来新题材只需在此登记一个专用函数（签名 (clean_text, context="", family="")）即可扩展，
# 不影响 analyze_structure 编排主流程。
STRUCTURE_EXTRACTORS = {
    "argument": _generic_outline_extractor,
    "case_study": _generic_outline_extractor,
    "comparison": _generic_outline_extractor,
    "narrative": _generic_outline_extractor,
    "qa": _generic_outline_extractor,
    "mixed": _generic_outline_extractor,
}


# ── A2 编排主入口 ──
def analyze_structure(clean_text: str, context: str = "") -> dict:
    """结构化提炼编排（A2 主入口）。

    1 次 LLM 识别结构家族；再 1 次 LLM 路由提取：
      - sop           → 填 `sop`（标准 SOP），`outline` 留空
      - 其它任何家族  → 填 `outline`（通用大纲），`sop` 留空
    sop / outline 互斥。任何 LLM 失败都降级，绝不抛出中断流水线。

    参数:
        clean_text: 净化(C2)后的纯文本
        context: 可选补充背景（标题/来源），仅辅助 LLM 理解

    返回:
        dict: {structure_type, sop, outline}
    """
    text = (clean_text or "").strip()
    if not text:
        return {
            "structure_type": "",
            "sop": dict(_EMPTY_SOP),
            "outline": dict(_EMPTY_OUTLINE),
        }

    structure_type = detect_structure_type(text, context)  # 内部已降级为 unknown

    if structure_type == "sop":
        sop = extract_sop(text, context)          # 内部已降级为空 SOP
        outline = dict(_EMPTY_OUTLINE)
    else:
        extractor = STRUCTURE_EXTRACTORS.get(structure_type, _generic_outline_extractor)
        fam = structure_type if structure_type != "unknown" else ""
        outline = extractor(text, context, family=fam)   # 内部已降级为空大纲
        sop = dict(_EMPTY_SOP)

    return {
        "structure_type": structure_type,
        "sop": sop,
        "outline": outline,
    }
