"""Albedo (Lian Zhen) · 形式线流水线 (v0.4.0)

形式线(Track B)与内容线(讲了什么)正交，管"怎么讲的"：
  钩子 / 叙事结构 / 节奏 / 人设 / 修辞话术 / 可复制模板 / 情绪曲线(弱代理) / 说服包装强度。
对应研究 docs/RESEARCH-FORM-TRACK-2026-07-16。

分层（用户拍板：全做 / 所有类型 / 修辞合并到形式线 / 情绪弹幕代理）：
  FT0 节奏+时长分层（纯函数零成本）
  FT1 钩子类型+首句强度
  FT2 叙事结构分段（带时间戳+每节目的）
  FT3 人设（信任基石/视角/标签）
  FT4 修辞话术 22 种全检（带 span）→ 同时是验真线的"单一来源"（truth_track 消费其规则库）
  FT5 可复制模板（标题公式+骨架，机器可读供凝华未来消费）
  FT6 情绪曲线（弹幕密度弱代理，诚实标 weak_signal）
  G1 说服包装强度（persuasion_polish，反向喂验真）
  G2 形式分析保真自检（form_faithfulness，复用 NLI 思路，防 LLM 编结构）

OCR 跨模态、跨视频人设累积：列入路线图（字段预留，逻辑未做）。

设计铁律（沿用内容线/验真线）：
  - 确定性：call_llm_json temperature=0 + 固定 JSON schema 枚举
  - 全程 try/except 包裹每步，失败→安全默认续跑，绝不整条中断
  - 纯函数步骤（FT0/FT6）不调 LLM，零成本
"""
from __future__ import annotations

import re
from typing import Optional

from core.llm import call_llm_json
from core.models import FormTrack


# ───────────────────────────────────────────────────────────────────────────
# 修辞规则库（单一来源：truth_track 也 import 此库消费，避免重复维护正则）
# ───────────────────────────────────────────────────────────────────────────
# 绝对化骗局话术（与验真线历史 _RED_FLAGS 同源，现归形式线）
_RED_FLAGS = [
    ("zero_basis_income", re.compile(r"零基础.{0,8}月入\s*\d+\s*万|月入\s*\d+\s*万.{0,8}零基础|小白.{0,8}月入\s*\d+\s*万")),
    ("guarantee", re.compile(r"(保证.{0,4}(赚|回本|过)|百分百|稳赚|包过|包教包会|稳赚不赔|躺赚)")),
    ("quick_result", re.compile(r"(\d+(?:\.\d+)?)\s*(天|周)\s*(?:内|就|可|能|便|左右)*\s*(?:见效|学会|出单|回本|赚)")),
    ("miracle_claim", re.compile(r"(永动机|一夜暴富|轻松月入|被动收入.{0,6}(万|元)|睡后收入)")),
]
# 水词（无出处权威暗示）
_WEASEL = [
    re.compile(r"(研究|调查|数据|实验|统计)\s*(表明|显示|证明|发现)"),
    re.compile(r"(专家|学者|教授|医生|业内人士|内部)\s*(说|指出|认为|透露)"),
    re.compile(r"(大多数|很多人|不少人|众人|大家|网友)\s*(都|普遍)?\s*(说|认为|表示|同意)"),
    re.compile(r"(据说|听闻|听说|网上说|网传|传言|据传)"),
    re.compile(r"(科学|权威|官方)\s*(证明|认证|推荐|认可)"),
]
# 模糊语（低承诺、可赖账）
_HEDGE_STRONG = re.compile(r"(可能|也许|或许|大概|应该|估计|说不定|疑似|据说|传言|网传|大概率是|八成)")
_HEDGE_WEAK = re.compile(r"(比较|相对|往往|一般来说|通常|一定程度上|大致|基本上|多半|倾向于|差不多|还算)")

# 轻量中文数字归一化（"十万"→"10万"）
_CN_NUM = {
    "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
}


def _norm_cn(text: str) -> str:
    return "".join(_CN_NUM.get(ch, ch) for ch in text)


def apply_rhetoric_rules(quote: str, blob: str = "") -> tuple:
    """共享修辞规则库（单一来源）：返回 (red_flags:list, weasel:bool, hedge_level:int)。

    形式线 FT4 用其兜底捕获绝对化骗局话术；验真线 truth_track.detect_rhetoric
    直接 import 本函数消费（避免两边各维护一套正则）。
    """
    q = _norm_cn(quote or "")
    b = _norm_cn(blob or "")
    red_flags = []
    for label, pat in _RED_FLAGS:
        if pat.search(q) or pat.search(b):
            red_flags.append(label)
    weasel = any(p.search(q) for p in _WEASEL)
    lvl = 0
    if _HEDGE_STRONG.search(q):
        lvl = 2
    elif _HEDGE_WEAK.search(q):
        lvl = 1
    return red_flags, weasel, lvl


def _ts_to_sec(ts: str) -> float:
    if not ts:
        return 0.0
    m = re.match(r"(\d{1,2}):(\d{2})", ts)
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + int(m.group(2))


def _sec_to_ts(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


# ───────────────────────────────────────────────────────────────────────────
# FT0 节奏 + 时长分层（纯函数，零成本）
# ───────────────────────────────────────────────────────────────────────────
def analyze_pacing(subtitle_lines: list) -> dict:
    """从字幕时间戳算语速/停顿/时长分层。无字幕→全默认。"""
    subs = [s for s in (subtitle_lines or []) if isinstance(s, dict) and s.get("text")]
    if not subs:
        return {"speech_rate_wpm": 0.0, "pause_count": 0, "avg_pause_s": 0.0,
                "length_tier": "unknown", "duration_s": 0.0, "n_lines": 0}
    subs_sorted = sorted(subs, key=lambda s: (s.get("start") or 0.0))
    total_chars = sum(len(s.get("text", "")) for s in subs_sorted)
    starts = [s.get("start") or 0.0 for s in subs_sorted]
    duration = max(starts) if starts else 0.0
    speech_rate = round(total_chars / (duration / 60.0), 1) if duration > 0 else 0.0
    # 停顿：相邻 start 间隔 > 3s 计为一次停顿
    gaps = [starts[i] - starts[i - 1] for i in range(1, len(starts))]
    pauses = [g for g in gaps if g > 3.0]
    avg_pause = round(sum(pauses) / len(pauses), 1) if pauses else 0.0
    # 时长分层
    if duration < 180:
        tier = "short"
    elif duration < 900:
        tier = "mid"
    else:
        tier = "long"
    return {
        "speech_rate_wpm": speech_rate,
        "pause_count": len(pauses),
        "avg_pause_s": avg_pause,
        "length_tier": tier,
        "duration_s": round(duration, 1),
        "n_lines": len(subs_sorted),
    }


# ───────────────────────────────────────────────────────────────────────────
# FT1 钩子类型 + 首句强度
# ───────────────────────────────────────────────────────────────────────────
_HOOK_SYSTEM = """你是视频钩子分析师。给定视频【前10秒】的字幕原文，判断开场钩子。
输出 JSON（不要解释）：
{
  "hook_type": "question|shock|statement|personal_story|contrarian|value_promise|curiosity_gap|other",
  "strength": 1-5 的整数（按"能否在前3秒摁住注意力"评，1弱5强）,
  "hook_text": "<必须取自给定前10秒字幕原文的某一句或拼接，逐字，不得编造>"
}
规则：hook_text 必须能在提供的字幕里找到（逐字或近义），严禁虚构。"""


def extract_hook(subtitle_lines: list, title: str, llm_kwargs: dict = None) -> dict:
    subs = [s for s in (subtitle_lines or []) if isinstance(s, dict)]
    first10 = [s for s in subs if (s.get("start") or 0.0) <= 10.0]
    if not first10:
        first10 = subs[:3]
    if not first10:
        return {"hook_type": "", "strength": 0, "hook_text": "", "ts": ""}
    sub_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in first10)
    user = f"视频标题：{title}\n\n前10秒字幕：\n{sub_text}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _HOOK_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=800, **(llm_kwargs or {}),
        )
        return {
            "hook_type": _str(data.get("hook_type")),
            "strength": _int(data.get("strength"), 0),
            "hook_text": _str(data.get("hook_text")),
            "ts": first10[0].get("ts", ""),
        }
    except Exception:
        return {"hook_type": "", "strength": 0, "hook_text": "", "ts": first10[0].get("ts", "")}


# ───────────────────────────────────────────────────────────────────────────
# FT2 叙事结构分段
# ───────────────────────────────────────────────────────────────────────────
_NARR_SYSTEM = """你是叙事结构分析师。给定字幕(带时间戳)，把视频切成 3-7 个叙事段落。
输出 JSON（不要解释）：
{
  "segments": [
    {"ts": "mm:ss（该段起始字幕的真实时间戳）", "title": "<段落标题>", "purpose": "<一句话说明这节在干嘛>"},
    ...
  ]
}
规则：ts 必须取自真实字幕时间戳；段落按时间顺序；purpose 用大白话。"""


def segment_narrative(subtitle_lines: list, content_type: str, llm_kwargs: dict = None) -> list:
    subs = [s for s in (subtitle_lines or []) if isinstance(s, dict) and s.get("text")]
    if not subs:
        return []
    sub_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subs)
    ctype = content_type or "generic"
    user = f"内容类型：{ctype}\n\n字幕全文：\n{sub_text}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _NARR_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=1500, **(llm_kwargs or {}),
        )
        segs = []
        for i, s in enumerate(data.get("segments") or []):
            if not isinstance(s, dict):
                continue
            ts = _str(s.get("ts"))
            segs.append({
                "ts": ts,
                "title": _str(s.get("title")),
                "purpose": _str(s.get("purpose")),
            })
        return segs
    except Exception:
        return []


# ───────────────────────────────────────────────────────────────────────────
# FT3 人设
# ───────────────────────────────────────────────────────────────────────────
_PERSONA_SYSTEM = """你是人设分析师。给定视频字幕/标题，分析创作者人设。
输出 JSON（不要解释）：
{
  "trust_base": "<观众为什么信他：专业背书|亲身实战|第三方权威|情感共鸣|不明>",
  "perspective": "<视角：第一人称经验分享|客观评测|行业内部|旁观吐槽>",
  "tags": ["<人设标签1>", "<标签2>"]
}"""


def detect_persona(subtitle_lines: list, title: str, clean_text: str, llm_kwargs: dict = None) -> dict:
    sub_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}"
                          for s in (subtitle_lines or []) if isinstance(s, dict))[:1500]
    user = f"标题：{title}\n\n字幕片段：\n{sub_text}\n\n全文片段：\n{(clean_text or '')[:800]}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _PERSONA_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=800, **(llm_kwargs or {}),
        )
        tags = data.get("tags") or []
        return {
            "trust_base": _str(data.get("trust_base")),
            "perspective": _str(data.get("perspective")),
            "tags": [_str(t) for t in tags if _str(t)],
        }
    except Exception:
        return {"trust_base": "", "perspective": "", "tags": []}


# ───────────────────────────────────────────────────────────────────────────
# FT4 修辞话术 22 种全检（带 span）+ 规则兜底绝对化骗局话术
# ───────────────────────────────────────────────────────────────────────────
_RHETORIC_SYSTEM = """你是修辞话术分析师。给定字幕(带时间戳)，识别视频使用的说服/修辞技巧。
从常见技巧中选（可多条）：反问、排比、夸张、对比、故事化、权威引用、数据堆砌、
恐惧诉求、稀缺 urgency、从众、锚定、互惠、承诺一致、喜好、社会认同、类推、比喻、
情绪共鸣、身份认同、对立框架、设问、悬念。
输出 JSON（不要解释）：
{
  "devices": [
    {"type": "<技巧名>", "span_text": "<字幕里的原句>", "ts": "mm:ss（该句时间戳，无则空）"},
    ...
  ]
}
规则：span_text 必须取自字幕原文；ts 取自真实字幕时间戳。"""


def detect_rhetoric_devices(subtitle_lines: list, clean_text: str, llm_kwargs: dict = None) -> list:
    """检测修辞话术（形式特征），返回 list[{type, span_text, ts}]。

    含两层：① LLM 识别 22 种说服技巧（形式/表达维度）② 规则兜底捕获绝对化骗局话术
    （apply_rhetoric_rules，truth_track 也消费此规则库）。两者合并，单一来源。
    """
    devices = []
    # ② 规则兜底：绝对化骗局话术（从 clean_text 抽片段）
    blob = clean_text or ""
    for label, pat in _RED_FLAGS:
        m = pat.search(_norm_cn(blob))
        if m:
            span = m.group(0)
            # 取匹配前后各 12 字作为上下文片段
            start = max(0, m.start() - 12)
            end = min(len(blob), m.end() + 12)
            devices.append({"type": f"绝对化话术:{label}", "span_text": blob[start:end], "ts": ""})
    weasel = any(p.search(_norm_cn(blob)) for p in _WEASEL)
    if weasel:
        devices.append({"type": "水词(无出处权威暗示)", "span_text": "", "ts": ""})

    # ① LLM 识别 22 种说服技巧
    subs = [s for s in (subtitle_lines or []) if isinstance(s, dict) and s.get("text")]
    if subs:
        sub_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subs)
        user = f"字幕全文：\n{sub_text}"
        try:
            data = call_llm_json(
                [{"role": "system", "content": _RHETORIC_SYSTEM},
                 {"role": "user", "content": user}],
                max_tokens=1800, **(llm_kwargs or {}),
            )
            for d in (data.get("devices") or []):
                if not isinstance(d, dict):
                    continue
                t = _str(d.get("type"))
                if not t:
                    continue
                devices.append({
                    "type": t,
                    "span_text": _str(d.get("span_text")),
                    "ts": _str(d.get("ts")),
                })
        except Exception:
            pass
    return devices


# ───────────────────────────────────────────────────────────────────────────
# FT5 可复制模板（机器可读，供凝华未来消费）
# ───────────────────────────────────────────────────────────────────────────
_TEMPLATE_SYSTEM = """你是内容结构模板提取器。给定视频(标题+结构分段+人设)，产出"可复制骨架"
——让别人能照着这个结构做同类视频。
输出 JSON（不要解释）：
{
  "title_formula": "<标题公式,如 '数字+痛点+结果'>",
  "section_skeleton": [{"ts": "mm:ss（真实字幕时间戳）", "purpose": "<这节干嘛,大白话>"}],
  "persona_tags": ["<可复用的人设标签>"]
}
规则：section_skeleton 的 ts 取真实字幕时间戳；机器可读，供下游自动生成视频脚本消费。"""


def build_reusable_template(title: str, segments: list, persona: dict, llm_kwargs: dict = None) -> dict:
    seg_text = "\n".join(f"[{s.get('ts', '')}] {s.get('title', '')}：{s.get('purpose', '')}"
                         for s in (segments or []))
    persona_tags = persona.get("tags") or [] if isinstance(persona, dict) else []
    user = f"标题：{title}\n\n结构分段：\n{seg_text}\n\n人设标签：{', '.join(persona_tags)}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _TEMPLATE_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=1200, **(llm_kwargs or {}),
        )
        skeleton = []
        for s in (data.get("section_skeleton") or []):
            if not isinstance(s, dict):
                continue
            skeleton.append({"ts": _str(s.get("ts")), "purpose": _str(s.get("purpose"))})
        return {
            "title_formula": _str(data.get("title_formula")),
            "section_skeleton": skeleton,
            "persona_tags": [_str(t) for t in (data.get("persona_tags") or []) if _str(t)],
        }
    except Exception:
        return {"title_formula": "", "section_skeleton": [], "persona_tags": []}


# ───────────────────────────────────────────────────────────────────────────
# FT6 情绪曲线（弹幕密度弱代理）
# ───────────────────────────────────────────────────────────────────────────
def emotion_proxy(danmaku: list) -> dict:
    """弹幕密度时间轴，作为情绪/留存曲线的弱代理。无弹幕→标 weak_signal+空。
    诚实声明：弹幕密度 ≠ 真实留存（受播放量/话题/文化影响）。
    """
    dms = [d for d in (danmaku or []) if isinstance(d, dict)]
    if not dms:
        return {"weak_signal": True, "timeline": [],
                "note": "无弹幕数据，情绪曲线无法代理（非真实留存曲线）"}
    buckets = {}
    for d in dms:
        t = d.get("time") or 0
        try:
            t = float(t)
        except (TypeError, ValueError):
            continue
        b = int(t // 30)
        buckets[b] = buckets.get(b, 0) + 1
    timeline = [{"t_sec": b * 30, "count": c} for b, c in sorted(buckets.items())]
    return {"weak_signal": True, "timeline": timeline,
            "note": "弹幕密度时间轴（弱代理，非真实留存曲线）"}


# ───────────────────────────────────────────────────────────────────────────
# G1 说服包装强度（反向喂验真）
# ───────────────────────────────────────────────────────────────────────────
def persuasion_polish(rhetoric_devices: list, persona: dict) -> float:
    """修辞越丰富 + 人设权威感越强 → 包装强度越高(0-1)。
    高包装 + 弱证据 = 验真线应额外加疑（真相错觉防御）。
    """
    n_dev = len(rhetoric_devices or [])
    trust = (persona or {}).get("trust_base", "")
    if trust in ("专业背书", "第三方权威"):
        authority = 1.0
    elif trust in ("亲身实战",):
        authority = 0.5
    else:
        authority = 0.3
    score = min(1.0, n_dev / 8.0 * 0.6 + authority * 0.4)
    return round(score, 2)


# ───────────────────────────────────────────────────────────────────────────
# G2 形式分析保真自检（防 LLM 编结构/hook）
# ───────────────────────────────────────────────────────────────────────────
def form_faithfulness(hook: dict, segments: list, subtitle_lines: list) -> dict:
    """检查 LLM 产出的形式结构是否能在字幕找到依据：
    - hook_text 必须出现在前10秒字幕
    - 每段 ts 必须是真实字幕时间戳
    无字幕→无法核查，标 checked=0（降级不报未支撑）。
    """
    subs = [s for s in (subtitle_lines or []) if isinstance(s, dict)]
    if not subs:
        return {"checked": 0, "ungrounded": []}
    subs_blob = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subs)
    ungrounded = []
    hook_text = (hook or {}).get("hook_text", "")
    if hook_text and hook_text not in subs_blob:
        ungrounded.append({"what": "hook_text", "text": hook_text})
    for seg in (segments or []):
        ts = (seg or {}).get("ts", "")
        if ts and ts not in subs_blob:
            ungrounded.append({"what": "segment_ts", "text": ts})
    checked = (1 if hook_text else 0) + len(segments or [])
    return {"checked": checked, "ungrounded": ungrounded}


# ───────────────────────────────────────────────────────────────────────────
# 表达力评分（三轴结论卡用）
# ───────────────────────────────────────────────────────────────────────────
def _compute_form_score(hook: dict, segments: list, persona: dict, pacing: dict) -> float:
    score = 0.0
    strength = (hook or {}).get("strength", 0) or 0
    score += min(strength, 5) / 5.0 * 0.3          # 钩子强度 30%
    if len(segments or []) >= 3:
        score += 0.3                                 # 结构完整 30%
    elif len(segments or []) > 0:
        score += 0.15
    if (persona or {}).get("trust_base"):
        score += 0.2                                 # 人设清晰 20%
    tier = (pacing or {}).get("length_tier", "")
    if tier in ("short", "mid", "long"):
        score += 0.2                                 # 有效节奏数据 20%
    return round(min(1.0, score), 2)


# ───────────────────────────────────────────────────────────────────────────
# 编排入口
# ───────────────────────────────────────────────────────────────────────────
def _run_form_track(
    inp,
    *,
    subtitle_lines: list = None,
    clean_text: str = "",
    key_sentences: list = None,
    content_type: str = "",
    llm_kwargs: dict = None,
) -> dict:
    """形式线主流程（所有视频类型通用）。

    参数：
      subtitle_lines: 字幕原文（FT0/FT1/FT2/FT4 锚定用；无则部分步骤降级）
      clean_text: 净化后全文（FT4 规则兜底话术）
      key_sentences: 内容线关键原话（预留，当前未用）
      content_type: 内容类型（FT2 分段策略参考）
    返回 FormTrack 字段对应的 dict。整体不抛。
    """
    subtitle_lines = subtitle_lines or []
    pacing = analyze_pacing(subtitle_lines)
    hook = extract_hook(subtitle_lines, getattr(inp, "title", "") or "", llm_kwargs)
    segments = segment_narrative(subtitle_lines, content_type, llm_kwargs)
    persona = detect_persona(subtitle_lines, getattr(inp, "title", "") or "", clean_text, llm_kwargs)
    devices = detect_rhetoric_devices(subtitle_lines, clean_text, llm_kwargs)
    template = build_reusable_template(getattr(inp, "title", "") or "", segments, persona, llm_kwargs)
    emotion = emotion_proxy(getattr(inp, "danmaku", []) or [])
    polish = persuasion_polish(devices, persona)
    faith = form_faithfulness(hook, segments, subtitle_lines)
    form_score = _compute_form_score(hook, segments, persona, pacing)
    return {
        "pacing": pacing,
        "hook": hook,
        "narrative_segments": segments,
        "persona": persona,
        "rhetoric_devices": devices,
        "reusable_template": template,
        "emotion_proxy": emotion,
        "persuasion_polish": polish,
        "form_faithfulness": faith,
        "form_score": form_score,
    }


# ── 小工具 ──
def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default
