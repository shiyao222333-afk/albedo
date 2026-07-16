"""Albedo (Lian Zhen) · Layer2 联网深验（MiniCheck 本地部署，TT6 实质）
========================================================================

用 MiniCheck（McGill-NLP，EMNLP2024）对"可证伪事实断言"逐条核验：
  claim + 同视频其他断言作证据语料 → supported / contradicted / neutral。

MiniCheck-Flan-T5-Large(7.7亿) 达 GPT-4 级(74.7% vs 75.3%)，本地确定性、不飘，
比自由 LLM 判真假稳得多（研究佐证见 docs/RESEARCH-TRUTH-METHODS-AUDIT）。

部署（用户本机，需联网一次）：
    pip install minicheck
    # 首次运行会自动下载 flan-t5-large 权重（~3GB，走 HuggingFace）
沙箱安装已验证可行（经 hf-mirror.com 镜像 + 本地源码安装 MiniCheck + 下载权重）；
此模块用 try/except 守卫——包未安装时 `available=False`，verify_claims_web 自动降级标 unverified（不臆断）。
权重缓存目录可用环境变量 MINICHECK_CACHE 指定（沙箱已下到 E:/tmp/minicheck_ckpts）。

设计：仅对 check_worthy 且 scope=public 且 factuality=factual 的断言逐条核验；
已判 contradicted（Layer1b 自相矛盾）的跳过，保矛盾结论。
"""
from __future__ import annotations

import logging
import os
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
        from minicheck.minicheck import MiniCheck
        cache_dir = os.environ.get("MINICHECK_CACHE") or None
        if cache_dir:
            _scorer = MiniCheck(model_name=MINICHECK_MODEL, cache_dir=cache_dir)
        else:
            _scorer = MiniCheck(model_name=MINICHECK_MODEL)
        logger.info("MiniCheck scorer 已加载（%s, cache=%s）", MINICHECK_MODEL, cache_dir)
    except Exception as e:
        logger.warning("MiniCheck scorer 加载失败：%s", e)
        _scorer = False  # 标记加载失败，避免反复尝试
    return _scorer if _scorer else None


def verify_claims(claims: list, corpus: list = None, max_claims: int = 40) -> bool:
    """对逐条断言就地写 accuracy / confidence / evidence_grade。

    Args:
        claims: truth_track 产出的 ClaimVerification 列表（dict，就地修改）。
        corpus: 证据语料（视频字幕原文 list[str]），作为 MiniCheck 的 docs；
                不传则退化为用其他断言的 quote（可能自指，真实路径应传字幕）。
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

    # 证据语料：优先用视频字幕原文（避免用断言自身当证据导致自指误判）
    if corpus and isinstance(corpus, list) and any(
            isinstance(x, str) and x.strip() for x in corpus):
        evidence = [str(x).strip() for x in corpus if str(x).strip()]
    else:
        evidence = [c.get("quote", "") for c in (claims or []) if c.get("quote")]
    # MiniCheck 需要非空 evidence corpus
    if not evidence:
        return False

    try:
        claims_text = [c.get("quote", "") for c in targets][:max_claims]
        # MiniCheck.score(docs=evidence_corpus, claims=to_check) -> (pred_labels, support_probs, used_chunks, per_chunk_probs)
        # pred_labels: 0=unsupported(无证据支持), 1=supported(有证据支持) —— 二分类
        out = scorer.score(docs=evidence, claims=claims_text)
        preds = out[0] if isinstance(out, (list, tuple)) else []
        probs = out[1] if len(out) > 1 else [0.0] * len(preds)
        for claim, pred, prob in zip(targets[:max_claims], preds, probs):
            if pred == 1:
                claim["accuracy"] = "supported"
                claim["confidence"] = round(float(prob), 4)
            else:  # unsupported：可能是 contradicted 或 neutral，MiniCheck 不区分，保守标 unverified
                claim["accuracy"] = "unverified"
                claim["confidence"] = 0.0
            claim["evidence_grade"] = "L4"
            claim["epistemic_status"] = claim["accuracy"]
            verdict = "supported(有证据支持)" if pred == 1 else "unsupported(无证据支持)"
            claim["reasoning"] = f"MiniCheck({MINICHECK_MODEL}) 判定：{verdict} (P={float(prob):.2f})"
        return True
    except Exception as e:
        logger.warning("MiniCheck 推理失败，降级 unverified：%s", e)
        for c in targets:
            if c.get("accuracy") != "contradicted":
                c["accuracy"] = "unverified"
                c["confidence"] = 0.0
        return False
