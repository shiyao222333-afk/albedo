"""Albedo (Lian Zhen) · 流水线编排 (C2 → C3 串联)

refine() 是 v0.1.0 的唯一对外入口：
  输入 AlbedoInput（对齐 Nigredo process() 输出）
  → C2 净化      purify()
  → #690 数值自洽 check_numeric_consistency() 生成 hint
  → C3 真实性     assess_truthfulness()（hint 注入 Prompt 辅助判定）
  → #691 变现     assess_monetization()
  → 由 label 推 status（true→accepted / suspect→suspect / false→rejected）
  → 组装最小 RefinedKnowledgeObject（v0.1.0 字段）返回

v0.1.0 仅填：clean_text / quality.truthfulness / status / monetization。
其余字段保留默认（数据模型已预留，未来版本补全，无需推倒重来）。
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


def refine(
    inp: AlbedoInput,
    *,
    llm_kwargs: Optional[dict] = None,
) -> RefinedKnowledgeObject:
    """认知精炼主入口：净化 + 多维评估 + 入库就绪对象组装。

    参数:
      inp:        对齐 Nigredo 的生料对象（text / text_type / 上下文信号）
      llm_kwargs: 可选透传 base_url / api_key / model 给 LLM（便于测试或本机指定 key）
                  不传则走 llm.py 的环境变量约定（KB_LLM_*，自动读 .env）

    返回:
      最小 RefinedKnowledgeObject（v0.1.0 字段已填）
    """
    # ── C2 净化（仅规整，保留卖课话术作为真实性证据）──
    clean_text = purify(inp.text, inp.text_type)

    # ── #690 数值自洽预检 → 生成 hint（注入真实性 Prompt）──
    num_check = check_numeric_consistency(clean_text)
    numeric_hint = num_check.summary

    # ── C3 真实性评估（LLM 单源；hint 作为补充证据）──
    truthfulness = assess_truthfulness(
        clean_text,
        context=_build_context(inp),
        numeric_hint=numeric_hint,
        **(llm_kwargs or {}),
    )

    # ── #691 变现检测（护栏：related 仅标注，不因此判假）──
    monetization = assess_monetization(clean_text)

    # ── 由真实性 label 推入库 status ──
    status = _LABEL_TO_STATUS.get(truthfulness.label, Status.SUSPECT.value)

    # ── 组装最小精炼对象（v0.1.0 字段）──
    return RefinedKnowledgeObject(
        input_ref=inp,
        clean_text=clean_text,
        quality=Quality(truthfulness=truthfulness),
        status=status,
        monetization=monetization,
    )


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
