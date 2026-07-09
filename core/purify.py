"""Albedo (Lian Zhen) · 内容净化 (C2)

职责（PROJECT_PLAN §5.1 T2）：
  - 按 text_type 分支处理：subtitle 走 ASR 清洗（去语气词/合并重复标点/修断句）；
    其他结构化文案（social_post/article/doc_ppt/doc_excel/webpage）仅做空白规整 + 直提炼。
  - 去广告话术：内置「卖课话术特征模式库」，但 MVP **只标注不删改**——
    卖课话术本身是真实性评估的证据，删了反而没法判真假（契合 ADR-005 变现护栏）。
  - 多语言翻译占位：MVP 不翻译，仅保留接口 detect_language() 占位，返回默认 "zh"。

对外暴露：
  - purify(text, text_type) -> 规整后文本
  - detect_sales_features(text) -> 命中的卖课特征标签列表（供 T3 assess 复用）
"""
from __future__ import annotations

import re

from core.models import TextType

# ── 卖课话术特征模式库（过度承诺 / 模糊施压 / 付费诱导 / 伪权威）──
# 形式：(label, compiled_regex)。命中即记录特征，净化阶段仅标注、不删改原文。
SALES_PATTERNS = [
    ("over_promise", re.compile(r"(保证|百分百|稳赚|月入\s*\d+\s*万|零基础.*变现|一天.*学会|包教包会)", re.I)),
    ("vague_pressure", re.compile(r"(名额有限|仅限今天|即将涨价|最后\s*\d+\s*个|错过.*再等一年|限时)", re.I)),
    ("paid_induce", re.compile(r"(私信|加微信|扫码|下单|报名|课程|训练营|付费|领取资料|资料包|会员)", re.I)),
    ("fake_authority", re.compile(r"(老师.*带你|亲自指导|内部.*秘籍|圈内.*不外传|不外传的)", re.I)),
]

# 字幕语气词 / 填充词（ASR 清洗用，subtitle 类型）
_FILLER_WORDS = re.compile(r"(嗯+|啊+|那个+|呃+|就是说+|对吧|是吧|哈+|哦+|额+)")
_REPEAT_PUNCT = re.compile(r"([。！？!?])\1+")
_MULTI_SPACE = re.compile(r"\s{2,}")


def detect_sales_features(text: str) -> list:
    """返回命中的卖课特征标签（可能重复出现也只记一次）。"""
    hits = []
    for label, pat in SALES_PATTERNS:
        if pat.search(text):
            hits.append(label)
    return hits


def purify_subtitle(text: str) -> str:
    """口语字幕 ASR 清洗：去多余语气词、合并重复标点、规整空白。"""
    t = _FILLER_WORDS.sub("", text)
    t = _REPEAT_PUNCT.sub(r"\1", t)
    t = _MULTI_SPACE.sub(" ", t).strip()
    return t


def purify(text: str, text_type: str) -> str:
    """按文本类型规整生料。MVP 不做实质性删改（保留证据）。"""
    if text_type == TextType.SUBTITLE.value:
        return purify_subtitle(text)
    # 结构化文案：仅规整空白，不破坏结构与证据
    return _MULTI_SPACE.sub(" ", text or "").strip()
