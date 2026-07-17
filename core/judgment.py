"""Albedo (Lian Zhen) · 证据链判定 (§6.2 判定方法论重做)
============================================================

替代 `assess.py` 自由 LLM 的 `truthfulness.label`，改为：
  **逐条断言证据 → Dempster-Shafer 证据融合 → 文档级确定性结论**。

设计要点（对应计划 §6.2）：
- 裁决由证据链推导，而非模型"感觉"——天然比自由标签更稳定、可解释。
- 纯 numpy，确定性，同输入必得同结论（根治 L4 三轮翻盘 suspect/suspect/true）。
- 复用 `D:\\albedo-old\\core\\ds_fusion.py` / `tms.py` 的数学（内联常量，不依赖旧 config）。

证据信号来源（来自 `core/truth_track.py` 的逐条 `ClaimVerification`）：
- Layer1b 自相矛盾 / MiniCheck 判伪 → accuracy="contradicted"（强假证据）
- MiniCheck 判真 → accuracy="supported"（强真证据，仅当 MiniCheck 已部署）
- Layer1a 话术红 flag → red_flags 非空（弱假证据）
- 模糊语 / 水词 → weasel_flag / hedge_level（弱不确定）
- 其余 → 无信号，mass 全给不确定（单源不臆断）
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, asdict
from typing import Optional

# ── 内联常量（原 albedo-old/config，避免依赖旧 config 模块）──
DS_CONFLICT_THRESHOLD = 0.6
DS_DISCOUNT = 0.9

# 单条证据 → 质量分配(BPA) 的 [m_true, m_false, m_uncertain]
_BPA_CONTRADICTED = np.array([0.05, 0.90, 0.05])  # 自相矛盾 / MiniCheck 判伪
_BPA_SUPPORTED = np.array([0.90, 0.05, 0.05])     # MiniCheck 判真
_BPA_RHETORIC = np.array([0.10, 0.45, 0.45])      # 话术红 flag（弱负面）
_BPA_HEDGE = np.array([0.20, 0.20, 0.60])         # 模糊语（弱不确定）
_BPA_UNCERTAIN = np.array([0.0, 0.0, 1.0])        # 无信号


@dataclass
class ClaimVerdict:
    """单条断言经证据融合后的判定。"""
    claim_id: str
    quote: str
    factuality: str
    scope: str
    accuracy: str
    belief_true: float
    belief_false: float
    uncertainty: float
    verdict: str  # supported / contested / uncertain / refuted


@dataclass
class DocumentVerdict:
    """文档级确定性结论（取代自由 LLM 的 truthfulness.label）。"""
    truth_label: str          # true / false / suspect
    epistemic_status: str     # corroborated / unverified / rejected
    confidence: float         # 0-1，believe_true
    belief_true: float
    belief_false: float
    uncertainty: float
    layer2_active: bool       # MiniCheck 是否实际跑过
    verification_level: str   # AF1：'externally_verified'(已联网深验) | 'self_consistent'(仅视频自洽·待外部核实)
    n_claims: int
    n_contradicted: int
    n_supported: int
    reasoning: str            # 可追溯的解释（报告用）


# ───────────────────────────────────────────────────────────────────────────
# Dempster-Shafer 证据融合（复用 ds_fusion.py 数学，内联常量）
# ───────────────────────────────────────────────────────────────────────────
def _dempster_rule(m1: np.ndarray, m2: np.ndarray) -> tuple[np.ndarray, float]:
    """Dempster 组合规则。返回 (m_combined, conflict_K)。"""
    K = m1[0] * m2[1] + m1[1] * m2[0]
    if np.isclose(K, 1.0):
        return np.array([0.5, 0.5, 0.0]), K
    norm = 1.0 / (1.0 - K)
    m_true = (m1[0] * m2[0] + m1[0] * m2[2] + m1[2] * m2[0]) * norm
    m_false = (m1[1] * m2[1] + m1[1] * m2[2] + m1[2] * m2[1]) * norm
    m_uncertain = (m1[2] * m2[2]) * norm
    return np.array([m_true, m_false, m_uncertain]), K


def _fuse_bpas(bpas: list) -> tuple:
    """融合一组质量向量，返回 (融合后 [m_true,m_false,m_uncertain], 总冲突K)。"""
    if not bpas:
        return np.array([0.0, 0.0, 1.0]), 0.0
    current = np.array(bpas[0], dtype=float).copy()
    total_conflict = 0.0
    for bpa in bpas[1:]:
        current, K = _dempster_rule(current, np.array(bpa, dtype=float))
        total_conflict = max(total_conflict, K)
    return current, total_conflict


# ───────────────────────────────────────────────────────────────────────────
# 单条断言：证据 → BPA → 融合判定
# ───────────────────────────────────────────────────────────────────────────
def _claim_signals(claim: dict) -> list:
    """把一条断言的各层证据信号转成 BPA 列表。"""
    signals = []
    accuracy = claim.get("accuracy", "unverified")
    if accuracy == "contradicted":
        signals.append(_BPA_CONTRADICTED)
    elif accuracy == "supported":
        signals.append(_BPA_SUPPORTED)

    red_flags = claim.get("red_flags") or []
    if red_flags:
        signals.append(_BPA_RHETORIC)

    hedge_level = claim.get("hedge_level", "none") or "none"
    weasel = bool(claim.get("weasel_flag", False))
    if weasel or hedge_level in ("high", "medium"):
        signals.append(_BPA_HEDGE)

    if not signals:
        signals.append(_BPA_UNCERTAIN)
    return signals


def _strip_supported(signals: list) -> list:
    """MiniCheck 未部署时，去掉 supported 信号（无法正向验证）。"""
    out = []
    for s in signals:
        if np.allclose(s, _BPA_SUPPORTED):
            continue
        out.append(s)
    if not out:
        out.append(_BPA_UNCERTAIN)
    return out


def judge_claim(claim: dict, claim_id: str = "", layer2_active: bool = True) -> ClaimVerdict:
    """单条断言的证据融合判定。"""
    sig = _claim_signals(claim) if layer2_active else _strip_supported(_claim_signals(claim))
    fused, _ = _fuse_bpas(sig)
    belief_true, belief_false, uncertainty = float(fused[0]), float(fused[1]), float(fused[2])
    margin = belief_true - belief_false

    if margin > 0.5:
        verdict = "supported"
    elif -0.2 < margin <= 0.2 and uncertainty > 0.6:
        verdict = "uncertain"
    elif margin <= -0.2:
        verdict = "refuted"
    else:
        verdict = "contested"

    return ClaimVerdict(
        claim_id=claim_id,
        quote=claim.get("quote", ""),
        factuality=claim.get("factuality", ""),
        scope=claim.get("scope", ""),
        accuracy=claim.get("accuracy", "unverified"),
        belief_true=round(belief_true, 4),
        belief_false=round(belief_false, 4),
        uncertainty=round(uncertainty, 4),
        verdict=verdict,
    )


# ───────────────────────────────────────────────────────────────────────────
# 文档级：逐条 BPA → 融合 → truth_label
# ───────────────────────────────────────────────────────────────────────────
def judge_document(claims: list, persuasion_polish: float = 0.0) -> DocumentVerdict:
    """把逐条断言证据聚合为文档级确定性结论。

    Args:
        claims: truth_track 产出的 ClaimVerification 列表（dict）。
        persuasion_polish: G1 反向桥的说服包装强度（0-1）。
    """
    claims = claims or []
    layer2_active = any(c.get("accuracy") == "supported" for c in claims)

    n = len(claims)
    n_contradicted = sum(1 for c in claims if c.get("accuracy") == "contradicted")
    n_supported = sum(1 for c in claims if c.get("accuracy") == "supported")

    if n == 0:
        return DocumentVerdict(
            truth_label="suspect", epistemic_status="unverified", confidence=0.0,
            belief_true=0.0, belief_false=0.0, uncertainty=1.0,
            layer2_active=False, verification_level="self_consistent",
            n_claims=0, n_contradicted=0, n_supported=0,
            reasoning="无断言可验（无字幕或纯观点），单源无法确认，标存疑。",
        )

    claim_bpas = []
    for c in claims:
        sig = _claim_signals(c) if layer2_active else _strip_supported(_claim_signals(c))
        fused, _ = _fuse_bpas(sig)
        claim_bpas.append(fused)

    doc_mass, total_conflict = _fuse_bpas(claim_bpas)
    belief_true, belief_false, uncertainty = float(doc_mass[0]), float(doc_mass[1]), float(doc_mass[2])
    margin = belief_true - belief_false

    if n_contradicted > 0 and margin < 0.15:
        truth_label = "false"
    elif belief_true > 0.6 and layer2_active and n_contradicted == 0:
        truth_label = "true"
    else:
        truth_label = "suspect"

    # G1 反向桥：高包装 + 未验证（MiniCheck 没跑）时，不轻信"真"
    if truth_label == "true" and persuasion_polish >= 0.7 and not layer2_active:
        truth_label = "suspect"

    epistemic_status = {"true": "corroborated", "suspect": "unverified", "false": "rejected"}[truth_label]
    confidence = round(belief_true, 4)
    # AF1：区分"来源自洽"与"外部已验证"。只有 Layer3 联网核查实际确认(web_status=verified)
    # 才算 externally_verified；MiniCheck 本地字幕核验 / 仅主张自洽都只是 self_consistent
    # （视频自洽一致，但待外部核实）。
    externally_verified = any(c.get("web_status") == "verified" for c in claims)
    verification_level = "externally_verified" if externally_verified else "self_consistent"

    reasoning = (
        f"逐条验真 {n} 条断言：{n_supported} 条获MiniCheck支持、{n_contradicted} 条被证伪"
        f"（自相矛盾/MiniCheck判伪）；文档级证据融合 belief_true={belief_true:.2f} "
        f"belief_false={belief_false:.2f} uncertainty={uncertainty:.2f}。"
        + (f"冲突K={total_conflict:.2f}。" if total_conflict > 0 else "")
        + f"结论={truth_label}（"
        + ("已联网核查确认(externally_verified)" if externally_verified
           else ("MiniCheck本地字幕核验·待联网外部核查" if layer2_active
                 else "MiniCheck未部署·仅视频自洽一致·待外部核实"))
        + "）"
        + (f"；G1反向桥：高包装(polish={persuasion_polish:.2f})未验证→不轻信真"
           if truth_label == "suspect" and persuasion_polish >= 0.7 else "")
    )

    return DocumentVerdict(
        truth_label=truth_label,
        epistemic_status=epistemic_status,
        confidence=confidence,
        belief_true=round(belief_true, 4),
        belief_false=round(belief_false, 4),
        uncertainty=round(uncertainty, 4),
        layer2_active=layer2_active,
        verification_level=verification_level,
        n_claims=n,
        n_contradicted=n_contradicted,
        n_supported=n_supported,
        reasoning=reasoning,
    )


def verdict_to_dict(v: DocumentVerdict) -> dict:
    return asdict(v)
