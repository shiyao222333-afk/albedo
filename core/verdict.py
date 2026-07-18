"""Albedo (Lian Zhen) · 整合信任算法（§2.6 单一信任出口）

取代旧 truth_track.aggregate 的 0-1 散分 + quality.truthfulness.label 双源漂移。
用户决策①「整合起来」：唯一函数 compute_verdict() 把
  - ① 证据链判定结论（judge_document 的 truth_label / evidence_grade）
  - ② 逐条话术(red_flags) / 矛盾(contradicted) 信号
  - ③ 证据分级（L1/L4，吸收原 evidence_grade）
  - ④ 说服包装强度 G1 反向桥
合并为一条流水线，输出 0-5 信任分 + epistemic_status + severity。

信任分尺度统一为 0-5（与熔知库一致，搜索排序直接用）；FPF 细信任分被本算法吸收，
FPF 模块正式取消（§2.6）。
"""
from __future__ import annotations


def compute_verdict(claims: list, truthfulness, persuasion_polish: float = 0.0) -> dict:
    """单一信任出口。

    参数:
        claims: truth_track 产出的 ClaimVerification 列表（dict）
        truthfulness: 含 .label(true/suspect/false) 与 .evidence_grade(L1-L4) 的对象
        persuasion_polish: 形式线 G1 说服包装强度 0-1

    返回:
        {"trust_score": float(0-5), "epistemic_status": str, "severity": str}
    """
    label = (getattr(truthfulness, "label", "") or "") if truthfulness else ""
    grade = (getattr(truthfulness, "evidence_grade", "") or "") if truthfulness else ""

    claims = claims or []
    n_contra = sum(1 for c in claims if c.get("accuracy") == "contradicted")
    n_red = sum(1 for c in claims if c.get("red_flags"))

    # —— 基础档（来自证据链判定结论）——
    if label == "false" or n_contra > 0:
        base, status, severity = 0.5, "rejected", "alert"
    elif label == "suspect":
        base, status, severity = 2.5, "unverified", ("warn" if n_red else "ok")
    else:  # true
        base, status, severity = 3.5, "substantiated", "ok"

    # —— 证据强度微调（吸收原 evidence_grade；L1/L4 两级）——
    if grade == "L4" and status in ("substantiated", "corroborated"):
        base = min(5.0, base + 1.0)
        if base >= 4.5:
            status = "corroborated"
    elif grade == "L1" and status == "substantiated":
        base = max(3.0, base - 0.5)

    # —— 话术额外下压（🔴B2 已废弃 aggregate 死逻辑，这里用真实信号）——
    if n_red > 0 and status != "rejected":
        base = max(0.2, base - 0.5)

    # —— G1 反向桥：高包装 + 未权威验证 → 额外谨慎（真相错觉防御）——
    if persuasion_polish >= 0.7 and status != "corroborated":
        base = max(0.2, base * 0.85)

    return {
        "trust_score": round(base, 1),
        "epistemic_status": status,
        "severity": severity,
    }
