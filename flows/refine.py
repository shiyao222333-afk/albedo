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

铁规矩（A5 决策）：
  - 全程 try/except 包裹每步 LLM，失败→安全默认续跑，绝不整条中断
  - assess.py（C3 数值 / 变现 / 真实性）v0.2.0 一行不动（MVP 占位，等 v0.3+ 大改）
  - 顺序：purify → 数值 hint → assess → A0 → A1 → A2 → A3 → A4
"""
from __future__ import annotations

from typing import Optional

from core.models import (
    AlbedoInput,
    RefinedKnowledgeObject,
    Quality,
    Truthfulness,
    Monetization,
    Status,
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

    # ── A0 摘要（内部已降级，不抛）──
    ctx_str = _context_str(inp)
    summary = summarize_content(clean_text, ctx_str)

    # ── A1 优点（内部已降级，不抛）──
    merits = analyze_merits(clean_text, ctx_str)

    # ── A2 结构（内部已降级，不抛）──
    structure = analyze_structure(clean_text, ctx_str)
    structure_type = structure.get("structure_type", "") or ""
    sop = structure.get("sop") or {}
    outline = structure.get("outline") or {}

    # ── A3 溯源（纯函数，缺字段留空不抛）──
    provenance = build_provenance(inp)

    # ── 由真实性 label 推入库 status ──
    status = _LABEL_TO_STATUS.get(truthfulness.label, Status.SUSPECT.value)

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
    )

    # ── A4 报告渲染（纯逻辑，不抛；失败兜底占位）──
    try:
        out.report = render_report(out, inp)
    except Exception:
        out.report = "（报告渲染未能生成）"

    return out


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
