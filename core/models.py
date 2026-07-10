"""Albedo (Lian Zhen) · 数据契约

炼真内部精炼知识对象 —— 从一开始就设计成「多维对象」，避免 v0.2.0 推倒重来。
v0.1.0 仅填: clean_text / quality.truthfulness / status / monetization.related
其余字段（copywriting/structure/logic/merits/sop/provenance/references/report/ingestion_meta）
在对应版本补全，数据模型保持不变。

对齐 PROJECT_PLAN.md §5.1。下游交熔知时读 ingestion_meta 直读直存（ADR-005）。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── 枚举常量（仅作构造期校验；dataclass 字段存其 .value 普通字符串）──
class TextType(str, Enum):
    SUBTITLE = "subtitle"      # 口语字幕（零碎、无段落，走 ASR 清洗）
    SOCIAL_POST = "social_post"
    ARTICLE = "article"
    DOC_PPT = "doc_ppt"
    DOC_EXCEL = "doc_excel"
    WEBPAGE = "webpage"        # 未来输入源，抓取由适配器完成


class TruthfulnessLabel(str, Enum):
    TRUE = "true"
    FALSE = "false"
    SUSPECT = "suspect"


class EvidenceGrade(str, Enum):
    L1 = "L1"   # 仅作者声称，无外部证据
    L2 = "L2"   # 单源弱证据（截图 / 个例）
    L3 = "L3"   # 多源或权威来源
    L4 = "L4"   # 可验证事实 / 公认可复现


class Status(str, Enum):
    ACCEPTED = "accepted"
    SUSPECT = "suspect"
    REJECTED = "rejected"


class MonetizationCategory(str, Enum):
    SELLING_COURSE = "selling_course"
    ECOMMERCE = "ecommerce"
    TOOL_PAID = "tool_paid"
    OTHER = "other"
    NONE = ""


# ── 输入：对齐 Nigredo process() 输出 ──
@dataclass
class AlbedoInput:
    text: str                                   # 净化前生料
    text_type: str = TextType.SUBTITLE.value    # 文本类型决定净化/评估策略
    signals: dict = field(default_factory=dict) # 平台归一化信号包(engagement/audience/sentiment)
    video_id: str = ""                          # Nigredo info.bvid
    title: str = ""
    up_name: str = ""
    source_url: str = ""


# ── 质量四维（维度① 真实性 驱动 status）──
@dataclass
class Truthfulness:
    label: str = ""                 # true / false / suspect
    score: int = 0                  # 0-100
    reasoning: str = ""
    evidence_grade: str = ""        # L1-L4


@dataclass
class DimensionScore:               # 文案/结构/逻辑 通用占位（v0.1.0 不填）
    score: int = 0
    reasoning: str = ""


@dataclass
class Quality:
    truthfulness: Truthfulness = field(default_factory=Truthfulness)
    copywriting: DimensionScore = field(default_factory=DimensionScore)
    structure: DimensionScore = field(default_factory=DimensionScore)
    logic: DimensionScore = field(default_factory=DimensionScore)


# ── 变现标注（内容「在卖什么」的客观属性，非业务线适配评分）──
@dataclass
class Monetization:
    related: bool = False
    category: str = ""
    note: str = ""


# ── 入库元数据（ADR-005）：预填熔知分面，入库直读直存 ──
@dataclass
class IngestionMeta:
    content_type: str = ""
    domain_udc_main: int = 0        # UDC 9 主类 0-9
    domain_udc_code: str = ""       # 细分码（可选）
    domain_label: str = ""
    temporal_nature: str = ""       # evergreen / timeboxed / transient
    epistemic_status: str = ""      # 由 quality.truthfulness.label 推
    trust_score: float = 0.0        # 0-1
    knowledge_type: str = ""
    target_platform: str = ""
    language: str = ""
    is_personal: bool = False
    access_level: str = ""
    lifecycle: str = ""             # 普通字段（已被 temporal_nature 取代分面地位）
    project_source: str = "albedo-refined"  # 普通字段（已被 epistemic_status 取代分面地位）


# ── 精炼知识对象（主内部表示）──
@dataclass
class RefinedKnowledgeObject:
    input_ref: AlbedoInput
    clean_text: str = ""
    summary: dict = field(default_factory=dict)   # A0 内容摘要（中性"讲什么"）：{gist, bullets, key_claims}
    quality: Quality = field(default_factory=Quality)
    merits: dict = field(default_factory=dict)
    sop: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    trust_score: float = 0.0
    status: str = ""
    monetization: Monetization = field(default_factory=Monetization)
    references: list = field(default_factory=list)
    report: str = ""
    ingestion_meta: IngestionMeta = field(default_factory=IngestionMeta)

    def to_dict(self) -> dict:
        """序列化为纯 dict（字段值均为 JSON 可序列化类型），用于落盘 data/out/<video_id>.json。"""
        return dataclasses.asdict(self)

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
