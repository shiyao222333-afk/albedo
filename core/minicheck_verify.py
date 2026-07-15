"""Albedo (Lian Zhen) · Layer2 联网深验（MiniCheck 本地部署，TT6 实质）
========================================================================

用 MiniCheck（McGill-NLP，EMNLP2024）对"可证伪事实断言"逐条核验：
  claim + 同视频其他断言作证据语料 → supported / contradicted / neutral。

MiniCheck-Flan-T5-Large(7.7亿) 达 GPT-4 级(74.7% vs 75.3%)，本地确定性、不飘，
比自由 LLM 判真假稳得多（研究佐证见 docs/RESEARCH-TRUTH-METHODS-AUDIT）。

部署（用户本机，需联网一次）：
    pip install minicheck
    # 首次运行会自动下载 flan-t5-large 权重（~1GB，走 HuggingFace）
本沙箱 PyPI 被代理拦截无法 pip install；此模块用 try/except 守卫——
包未安装时 `available=False`，verify_claims_web 自动降级标 unverified（不臆断）。

设计：仅对 check_worthy 且 scope=public 且 factuality=factual 的断言逐条核验；
已判 contradicted（Layer1b 自相矛盾）的跳过，保矛盾结论。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("albedo.minicheck")

MINICHECK_MODEL = "flan-t5-large"  # 7.7亿参数，GPU/CPU 均可；RTX3080 跑得更顺

_available: Optional[bool] = None
_scorer = None


def is_available() -> bool:
    """MiniCheck 包是否可用（懒检测）。"""
    global _available
    if _available is None:
        try:
            import minicheck  # noqa: F401
            _available = True
        except Exception as e:
            _available = False
            logger.warning("MiniCheck 未安装，Layer2 降级为 unverified：%s", e)
    return _available


def _get_scorer():
    """懒加载 MiniCheck scorer（只加载一次）。"""
    global _scorer
    if _scorer is not None:
        return _scorer
    if not is_available():
        return None
    try:
        from minicheck import MiniCheck
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _scorer = MiniCheck(model_name=MINICHECK_MODEL, device=device)
        logger.info("MiniCheck scorer 已加载（%s @ %s）", MINICHECK_MODEL, device)
    except Exception as e:
        logger.warning("MiniCheck scorer 加载失败：%s", e)
        _scorer = False  # 标记加载失败，避免反复尝试
    return _scorer if _scorer else None


def verify_claims(claims: list, max_claims: int = 40) -> bool:
    """对逐条断言就地写 accuracy / confidence / evidence_grade。

    Args:
        claims: truth_track 产出的 ClaimVerification 列表（dict，就地修改）。
    Returns:
        是否实际跑了 MiniCheck（True=已核验；False=降级）。
    """
    scorer = _get_scorer()
    if scorer is None:
        return False

    targets = [
        c for c in (claims or [])
        if c.get("check_worthy") and c.get("scope") == "public"
        and c.get("factuality") == "factual"
        and c.get("accuracy") != "contradicted"
    ]
    if not targets:
        return False

    corpus = [c.get("quote", "") for c in (claims or []) if c.get("quote")]
    # MiniCheck 需要非空 evidence corpus
    if not corpus:
        return False

    try:
        claims_text = [c.get("quote", "") for c in targets][:max_claims]
        preds, _, _ = scorer.predict(claims=claims_text, corpus=corpus, batch_size=8)
        for claim, pred in zip(targets[:max_claims], preds):
            p = (pred or "").strip().lower()
            if p == "supported":
                claim["accuracy"] = "supported"
                claim["confidence"] = 0.9
            elif p == "contradicted":
                claim["accuracy"] = "contradicted"
                claim["confidence"] = 0.9
            else:  # neutral
                claim["accuracy"] = "unverified"
                claim["confidence"] = 0.0
            claim["evidence_grade"] = "L4"
            claim["epistemic_status"] = claim["accuracy"]
            claim["reasoning"] = f"MiniCheck({MINICHECK_MODEL}) 判定：{pred}"
        return True
    except Exception as e:
        logger.warning("MiniCheck 推理失败，降级 unverified：%s", e)
        for c in targets:
            if c.get("accuracy") != "contradicted":
                c["accuracy"] = "unverified"
                c["confidence"] = 0.0
        return False
