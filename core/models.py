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


# ── 验真逐条维度枚举（v0.3.0 验真环节，对应 V2/V3 研究的三维度 + 补漏）──
class FactualityLabel(str, Enum):
    FACTUAL = "factual"   # 可证伪事实主张（走验真）
    OPINION = "opinion"   # 主观价值判断（不验真假，评支撑度/自洽；给观点判真假是范畴错误）
    MIXED = "mixed"       # 混合声称（前半事实后半观点，最难）


class ScopeLabel(str, Enum):
    PERSONAL = "personal"  # 第一人称经验（不可外部证伪，判内部自洽）
    PUBLIC = "public"      # 可外部验证的公开断言（走联网深验）


class ValidityClass(str, Enum):
    EVERGREEN = "evergreen"   # 恒真（原理 / 概念）
    TIMEBOXED = "timeboxed"   # 限时（平台规则 / 价格 / 版本，会变 → 结论有时效）
    TRANSIENT = "transient"   # 易逝（短期玩法 / 热点）


class AccuracyLabel(str, Enum):
    SUPPORTED = "supported"       # 被证据支撑（Layer2 MiniCheck）
    CONTRADICTED = "contradicted" # 被证据推翻（Layer2 MiniCheck / Layer1b 自相矛盾）
    UNVERIFIED = "unverified"     # 没查（默认，非假；V3 遗漏5 保守校准）


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
    # —— 内容线结构化信号（2026-07-15 新增，全部可选，向后兼容旧调用）——
    # 来源：Nigredo 中转 .md 经 parser 解析后填入；非字幕输入可留空走通用路径。
    subtitle_lines: list = field(default_factory=list)   # [{ts:"mm:ss", start:float, text:str}] 解析 # 字幕 段
    highlights: list = field(default_factory=list)       # [{ts:"mm:ss", start:float, content:str}] 解析 # 高光时间点
    danmaku: list = field(default_factory=list)          # [{time:float, text:str}] 解析 # 弹幕
    comments_pinned: list = field(default_factory=list)  # [{user, likes, text, pin_type}]
    comments_top: list = field(default_factory=list)     # [{user, likes, text}]
    ai_conclusion: str = ""                              # # AI 摘要 原文
    play_analysis: dict = field(default_factory=dict)    # 三秒退出率/平均播放时长/完播率等


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


# ── 验真逐条记录（v0.3.0 验真环节）──
# 每条原子断言一张"验真身份证"：来自字幕原话 → 分类(事实/观点, 个人/公开)
# → 防瞎编(Layer0.5) → 话术/自相矛盾/时效(Layer1) → 逐条验真(Layer2, MiniCheck 本地)。
# 设计见 docs/RESEARCH-TRUTH-VERIFICATION-V2/V3。OCR 跨模态与跨视频信用累积排路线图。
@dataclass
class ClaimVerification:
    claim_id: str = ""                 # 稳定 id: c0 / c1 / ...
    quote: str = ""                    # 原话（锚定 key_sentences / 字幕，已带 ts）
    ts: str = ""                       # 字幕时间戳 mm:ss
    start: float = 0.0                 # 秒（锚定定位用）
    # —— V2 三维度 ——
    factuality: str = ""               # factual / opinion / mixed
    scope: str = ""                    # personal / public
    check_worthy: bool = False         # 经验主张(False) vs 可证伪事实主张(True)（V2 决策2 放过经验）
    # —— Layer2 逐条验真结果（MiniCheck 本地；沙箱标 unverified）——
    accuracy: str = ""                 # supported / contradicted / unverified
    evidence_grade: str = ""           # L1-L4
    epistemic_status: str = ""         # 落熔知 epistemic_status（证据强度轴）
    confidence: float = 0.0            # 校准置信度 0-1（默认保守 unverified）
    # —— V3 补漏字段 ——
    faithfulness: str = "grounded"     # grounded / ungrounded（Layer0.5 防 LLM 瞎编断言）
    contradicts_with: list = field(default_factory=list)  # [{claim_id, ts}]（Layer1b 自相矛盾）
    verified_date: str = ""            # 核查日（Layer1c 时效）
    validity_class: str = ""           # evergreen / timeboxed / transient
    is_visual_claim: bool = False      # 画面主张（当前 unverified，OCR 排路线图）
    cross_modal_contradiction: bool = False  # 字幕 vs 画面文字矛盾（OCR 排路线图）
    hedge_level: int = 0               # 0 绝对 / 1 弱保留 / 2 强模糊（V3 遗漏6 话术逃避）
    weasel_flag: bool = False          # 水词（"研究表明""专家说"无出处）
    red_flags: list = field(default_factory=list)  # 绝对化骗局话术标签（如 guarantee / miracle_claim）
    evidence: str = ""                 # 支撑/反证（Layer2）
    reasoning: str = ""                # 人话解释（标可疑必须能点开看原因）
    creator_id: str = ""               # 跨视频信用（V3 遗漏7，聚合排路线图 v0.3.x）
    creator_rep_delta: float = 0.0     # 本视频对 UP 主信用的 ±贡献（聚合排路线图）


# ── 精炼知识对象（主内部表示）──
@dataclass
class RefinedKnowledgeObject:
    input_ref: AlbedoInput
    clean_text: str = ""
    summary: dict = field(default_factory=dict)   # A0 内容摘要（中性"讲什么"）：{gist, bullets, key_claims}
    # —— 内容线（2026-07-15 新增，仅字幕输入填充）——
    content_type: str = ""                          # classify 结果: tutorial/tool_review/knowledge/opinion/entertainment/narrative/unknown
    key_sentences: list = field(default_factory=list)   # Route A 关键原话兜底 [{ts, text}]（原话不动）
    content_extract: dict = field(default_factory=dict) # 按类型萃取: sop/decision/claim/concept（见 core/classify.py 路由）
    highlight_blocks: list = field(default_factory=list) # 高光上下文块 [{ts, subtitle_window:[...], danmaku:[...], comments:[...]}]
    grounding: dict = field(default_factory=dict)   # 保真自检: {checked, ungrounded:[{text, ts}]}（总结是否被字幕原文支撑）
    # —— 验真逐条（v0.3.0，仅字幕/通用路径填充）——
    claim_verifications: list = field(default_factory=list)  # list[ClaimVerification] 逐条验真记录
    truth_track: dict = field(default_factory=dict)          # 验真聚合摘要（结论卡 + 报告章节用）
    quality: Quality = field(default_factory=Quality)
    merits: dict = field(default_factory=dict)
    sop: dict = field(default_factory=dict)
    structure_type: str = ""    # A2.1 识别的内容结构家族: sop/argument/case_study/comparison/narrative/qa/mixed/unknown
    outline: dict = field(default_factory=dict)   # A2.3 非 sop 型产出的内容大纲 {overview, sections:[{subtitle, points}]}；unknown 回退通用大纲
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
