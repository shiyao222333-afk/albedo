"""Albedo (Lian Zhen) · 流水线编排 (v0.2.0 切片 A 收口)

refine() 是 v0.2.0 的完整对外入口，串联：
  C2 净化      purify()
  #690 数值自洽 check_numeric_consistency() → hint（注入真实性 Prompt）
  C3 真实性     assess_truthfulness()（hint 辅助；失败时降级 suspect，不阻断）
  #691 变现     assess_monetization()（护栏：related 仅标注，不因此判假）
  A0 摘要       summarize_content()
  A1 优点       analyze_merits()
  A2 结构       analyze_structure()
  A3 溯源       build_provenance()
  A4 报告       render_report() → 写入 out.report
组装完整 RefinedKnowledgeObject 返回。

AI 设计决策（A5，非用户指令，待确认）：
  - 全程 try/except 包裹每步 LLM，失败→安全默认续跑，绝不整条中断
  - assess.py（C3 数值 / 变现 / 真实性）v0.2.0 作为 MVP 占位，验真结论改由 truth_track 证据链推导（§6.2，取代自由 LLM）
  - 顺序：purify → 数值 hint → assess → A0 → A1 → A2 → A3 → A4
"""
from __future__ import annotations

from typing import Optional

from core.models import (
    AlbedoInput,
    RefinedKnowledgeObject,
    FormTrack,
    Quality,
    Truthfulness,
    Monetization,
    Status,
    IngestionMeta,
)
from core.purify import purify
from core.assess import (
    assess_truthfulness,
    check_numeric_consistency,
    assess_monetization,
)
from core.summary import summarize_content
from core.merit import analyze_merits
from core.structure import analyze_structure
from core.provenance import build_provenance
from core.report import render_report
from core.classify import classify_content_type
from core.content_track import (
    extract_key_sentences,
    build_highlight_blocks,
    extract_by_type,
)
from core.grounding import check_grounding
from core.truth_track import _run_truth_track
from core.form_track import _run_form_track
from core.judgment import judge_document  # §6.2 证据链判定（取代 assess 自由 LLM label）


# 维度① 真实性 label → 入库 status 映射
_LABEL_TO_STATUS = {
    "true": Status.ACCEPTED.value,
    "suspect": Status.SUSPECT.value,
    "false": Status.REJECTED.value,
}


def _build_context(inp: AlbedoInput) -> dict:
    """从 AlbedoInput 抽取评估上下文（平台 / 作者 / 标题），注入真实性 Prompt。

    平台信息优先取 signals.platform（Nigredo 归一化信号包），缺省标「未知」。
    """
    signals = inp.signals or {}
    return {
        "platform": signals.get("platform") or "未知",
        "up_name": inp.up_name or "未知",
        "title": inp.title or "未知",
    }


def _context_str(inp: AlbedoInput) -> str:
    """可读上下文字符串，传给 A0/A1/A2（它们接受 str 补充背景）。

    缺失字段自动省略，避免向模型喂无意义占位。
    """
    signals = inp.signals or {}
    parts = []
    platform = signals.get("platform")
    if platform:
        parts.append(f"来源平台：{platform}")
    if inp.up_name:
        parts.append(f"作者：{inp.up_name}")
    if inp.title:
        parts.append(f"标题：{inp.title}")
    return "；".join(parts)


def refine(
    inp: AlbedoInput,
    *,
    llm_kwargs: Optional[dict] = None,
) -> RefinedKnowledgeObject:
    """认知精炼主入口：净化 + 多维评估 + 摘要/优点/结构/溯源 + 报告组装。

    参数:
      inp:        对齐 Nigredo 的生料对象（text / text_type / 上下文信号）
      llm_kwargs: 可选透传 base_url / api_key / model 给 LLM（便于测试或本机指定 key）
                  不传则走 llm.py 的环境变量约定（KB_LLM_*，自动读 .env）

    返回:
      完整 RefinedKnowledgeObject（含 report 字段，即对外主交付物）
    """
    llm_kwargs = llm_kwargs or {}

    # ── C2 净化（仅规整，保留卖课话术作为真实性证据）──
    clean_text = purify(inp.text, inp.text_type)

    # ── #690 数值自洽预检 → 生成 hint（注入真实性 Prompt）──
    num_check = check_numeric_consistency(clean_text)
    numeric_hint = num_check.summary

    # ── C3 真实性评估（LLM 单源；hint 作为补充证据；失败降级 suspect 不阻断）──
    try:
        truthfulness = assess_truthfulness(
            clean_text,
            context=_build_context(inp),
            numeric_hint=numeric_hint,
            **llm_kwargs,
        )
    except Exception:
        truthfulness = Truthfulness(
            label="suspect",
            score=50,
            reasoning="（真实性评估未能生成，已降级为存疑）",
            evidence_grade="L1",
        )

    # ── #691 变现检测（护栏：related 仅标注，不因此判假）──
    try:
        monetization = assess_monetization(clean_text)
    except Exception:
        monetization = Monetization(related=False)

    # ── 内容线默认（字幕未结构化时走通用路径）──
    content_type = ""
    key_sentences = []
    content_extract = {}
    highlight_blocks = []
    grounding = {}
    use_content_track = (inp.text_type == "subtitle" and bool(inp.subtitle_lines))
    if use_content_track:
        # 字幕输入 → 内容线：分类 / 关键句+摘要 / 高光块 / 按类型萃取 / 保真自检
        ct = _run_content_track(inp, llm_kwargs)
        summary = ct["summary"]
        merits = {}  # 内容线不单独产 merits，优点已融入各类型萃取
        content_type = ct["content_type"]
        key_sentences = ct["key_sentences"]
        content_extract = ct["content_extract"]
        highlight_blocks = ct["highlight_blocks"]
        grounding = ct["grounding"]
        # sop/outline 字段映射（旧报告路径兼容；内容线报告优先读 content_extract）
        if content_type == "tutorial" and isinstance(content_extract, dict):
            sop = {k: v for k, v in content_extract.items() if k != "kind"}
            structure_type = "sop"
            outline = {}
        elif content_type == "narrative" and isinstance(content_extract, dict):
            outline = {k: v for k, v in content_extract.items() if k != "kind"}
            structure_type = "narrative"
            sop = {}
        else:
            sop = {}
            outline = {}
            structure_type = content_type or ""
    else:
        # ── 旧通用路径 A0/A1/A2（非字幕输入）──
        ctx_str = _context_str(inp)
        summary = summarize_content(clean_text, ctx_str)

        # ── A1 优点（内部已降级，不抛）──
        merits = analyze_merits(clean_text, ctx_str)

        # ── A2 结构（内部已降级，不抛）──
        structure = analyze_structure(clean_text, ctx_str)
        structure_type = structure.get("structure_type", "") or ""
        sop = structure.get("sop") or {}
        outline = structure.get("outline") or {}

    # ── 形式线（v0.4.0, Track B）：所有类型都跑，管"怎么讲的"（钩子/结构/节奏/人设/修辞/模板）──
    ft = _run_form_track(
        inp, subtitle_lines=inp.subtitle_lines, clean_text=clean_text,
        key_sentences=key_sentences, content_type=content_type, llm_kwargs=llm_kwargs,
    )
    form_track = FormTrack(**ft)
    form_score = ft.get("form_score", 0.0)

    # ── 验真环节（v0.3.0）：逐条断言验真（Layer0.5 防瞎编 + Layer1 不联网快筛；
    #    Layer2 联网深验 MiniCheck 沙箱标 unverified，待本机部署启用）──
    tt = _run_truth_track(
        inp, key_sentences=key_sentences, subtitle_lines=inp.subtitle_lines,
        clean_text=clean_text, llm_kwargs=llm_kwargs,
        persuasion_polish=ft.get("persuasion_polish", 0.0),
    )
    claim_verifications = tt["claims"]
    truth_track = tt["truth_track"]

    # ── §6.2 判定方法论重做：用证据链(D-S融合)推导 truth_label，取代 assess 自由 LLM ──
    # assess.py 退为"参考"（数值/变现/启发式评分），判定结论改由确定性证据链给出，
    # 根治"同输入三轮翻盘 suspect/suspect/true"。
    try:
        verdict = judge_document(
            claim_verifications,
            persuasion_polish=ft.get("persuasion_polish", 0.0),
        )
        truthfulness.label = verdict.truth_label
        truthfulness.score = int(verdict.confidence * 100)
        truthfulness.reasoning = verdict.reasoning
        truthfulness.evidence_grade = "L4" if verdict.layer2_active else "L1"
    except Exception:
        # 判定模块异常不阻断，回退 assess 的降级结果
        pass

    # ── A3 溯源（纯函数，缺字段留空不抛）──
    provenance = build_provenance(inp)

    # ── 由真实性 label 推入库 status（验真矛盾/话术信号上调为存疑，保守不误伤）──
    status = _LABEL_TO_STATUS.get(truthfulness.label, Status.SUSPECT.value)
    if truth_track.get("severity") in ("alert", "warn"):
        status = Status.SUSPECT.value

    # ── 组装完整精炼对象（v0.2.0 字段全填；copywriting/structure/logic 留默认 DimensionScore，
    #    trust_score 留 0.0 待 FPF 模块；references/ingestion_meta 切片 B 补全）──
    out = RefinedKnowledgeObject(
        input_ref=inp,
        clean_text=clean_text,
        summary=summary,
        quality=Quality(truthfulness=truthfulness),
        merits=merits,
        sop=sop,
        structure_type=structure_type,
        outline=outline,
        provenance=provenance,
        status=status,
        monetization=monetization,
        content_type=content_type,
        key_sentences=key_sentences,
        content_extract=content_extract,
        highlight_blocks=highlight_blocks,
        grounding=grounding,
        claim_verifications=claim_verifications,
        truth_track=truth_track,
        form_track=form_track,
        form_score=form_score,
        trust_score=truth_track.get("trust_score", 0.0),
        ingestion_meta=IngestionMeta(
            content_type=content_type,
            epistemic_status=truth_track.get("epistemic_status", ""),
            is_personal=truth_track.get("is_personal", False),
            trust_score=truth_track.get("trust_score", 0.0),
        ),
    )

    # ── A4 报告渲染（纯逻辑，不抛；失败兜底占位）──
    try:
        out.report = render_report(out, inp)
    except Exception:
        out.report = "（报告渲染未能生成）"

    return out


def _run_content_track(inp: AlbedoInput, llm_kwargs: dict) -> dict:
    """内容线主流程（字幕输入）：分类 → 关键句+摘要 → 高光块 → 按类型萃取 → 保真自检。

    每步独立 try/except 降级（已在各子模块内），整体不抛。
    """
    content_type = classify_content_type(
        inp.title, inp.subtitle_lines, inp.ai_conclusion, llm_kwargs
    )
    ks = extract_key_sentences(
        inp.subtitle_lines, inp.title, inp.ai_conclusion, llm_kwargs
    )
    key_sentences = ks.get("key_sentences", [])
    summary = ks.get("summary", {})
    highlight_blocks = build_highlight_blocks(
        inp.highlights, inp.subtitle_lines, inp.danmaku,
        inp.comments_top, inp.comments_pinned, window=15,
    )
    content_extract = extract_by_type(
        content_type, key_sentences, summary, highlight_blocks,
        inp.title, inp.ai_conclusion, llm_kwargs,
    )
    grounding = check_grounding(
        summary.get("bullets", []), inp.subtitle_lines, llm_kwargs
    )
    return {
        "content_type": content_type,
        "key_sentences": key_sentences,
        "summary": summary,
        "highlight_blocks": highlight_blocks,
        "content_extract": content_extract,
        "grounding": grounding,
    }


def refine_text(
    text: str,
    *,
    text_type: str = "subtitle",
    title: str = "",
    up_name: str = "",
    source_url: str = "",
    video_id: str = "",
    signals: Optional[dict] = None,
    llm_kwargs: Optional[dict] = None,
) -> RefinedKnowledgeObject:
    """便捷封装：直接从原始文本精炼，免去手动构造 AlbedoInput。"""
    inp = AlbedoInput(
        text=text,
        text_type=text_type,
        signals=signals or {},
        video_id=video_id,
        title=title,
        up_name=up_name,
        source_url=source_url,
    )
    return refine(inp, llm_kwargs=llm_kwargs)
