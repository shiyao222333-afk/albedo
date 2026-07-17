"""Albedo (Lian Zhen) · Layer2 联网深验（本地 NLI 模型，TT6 实质）
========================================================================

⚠️ MiniCheck 路线已弃用（沙箱部署从未真跑通 + 中文能力弱）。
现用 **mDeBERTa-XNLI**（MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7，
多语言 NLI，含中文，base~300M，本地确定性、不飘）做逐条验真。

为什么换（2026-07-17 用户拍板）：
  - 不需要 nltk punkt（MiniCheck 的中文分句词典沙箱缺失导致静默降级 suspect）
  - 模型小（~330M）、下载快、遗留代码 nli_detector.py 已用过同款
  - 多语言含中文，对本机中文视频字幕友好

NLI 三分类映射：
  premise = 视频字幕原文（证据语料）；hypothesis = 单条主张
  entailment(被字幕支持)   -> accuracy="supported"
  contradiction(被字幕反驳) -> accuracy="contradicted"
  neutral(字幕无相关信息)   -> accuracy="unverified"（证据不足，保守不臆断）

部署（本机一次）：权重下到 LAYER2_MODEL_DIR（默认 E:/tmp/mdeberta_xnli）。
此模块用 try/except 守卫——模型未下载时 available=False，verify_claims 自动降级标 unverified。
文件名暂沿用 minicheck_verify.py 以减少 import 改动；语义已切换，后续统一重命名为 layer2_verify.py。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import torch
import torch.nn.functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger("albedo.layer2")

MODEL_NAME = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
LOCAL_DIR = os.environ.get("LAYER2_MODEL_DIR") or "E:/tmp/mdeberta_xnli"
CACHE_DIR = os.environ.get("LAYER2_CACHE_DIR") or "E:/tmp/mdeberta_cache"

_tokenizer = None
_model = None


def is_available() -> bool:
    """transformers/torch 是否可用（懒检测）。"""
    try:
        import transformers  # noqa: F401
        return True
    except Exception as e:
        logger.warning("transformers 未安装，Layer2 降级为 unverified：%s", e)
        return False


def _load():
    """懒加载 mDeBERTa-XNLI（只加载一次，local_files_only 不联网）。"""
    global _tokenizer, _model
    if _model is not None:
        return _model
    if not is_available():
        return None
    try:
        _tokenizer = AutoTokenizer.from_pretrained(LOCAL_DIR, cache_dir=CACHE_DIR, local_files_only=True)
        _model = AutoModelForSequenceClassification.from_pretrained(LOCAL_DIR, cache_dir=CACHE_DIR, local_files_only=True)
        if torch.cuda.is_available():
            _model = _model.cuda()
        _model.eval()
        logger.info("Layer2 mDeBERTa-XNLI 已加载（local=%s, gpu=%s）", LOCAL_DIR, torch.cuda.is_available())
    except Exception as e:
        logger.warning("Layer2 模型加载失败（权重未下全？）：%s", e)
        _model = False
    return _model if _model else None


def verify_claims(claims: list, corpus: list = None, max_claims: int = 40) -> bool:
    """对逐条断言就地写 accuracy / confidence / evidence_grade / epistemic_status / reasoning。

    与旧 MiniCheck 版接口完全一致：claims 为 ClaimVerification 列表（就地修改），
    corpus 为字幕原文 list[str]。返回是否实际跑了模型（False=降级 unverified）。
    """
    model = _load()
    if model is None:
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
    if corpus and isinstance(corpus, list) and any(isinstance(x, str) and x.strip() for x in corpus):
        evidence = [str(x).strip() for x in corpus if str(x).strip()]
    else:
        evidence = [c.get("quote", "") for c in (claims or []) if c.get("quote")]
    if not evidence:
        return False

    premise = "\n".join(evidence)
    id2label = model.config.id2label
    labels = [id2label[i] for i in range(len(id2label))]
    try:
        ent_i, con_i, neu_i = labels.index("entailment"), labels.index("contradiction"), labels.index("neutral")
    except ValueError:
        logger.warning("模型标签非标准 NLI，降级：%s", labels)
        return False

    try:
        for c in targets[:max_claims]:
            hyp = c.get("quote", "")
            if not hyp:
                continue
            inputs = _tokenizer(premise, hyp, return_tensors="pt", truncation=True, max_length=512)
            if torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}
            with torch.no_grad():
                logits = model(**inputs).logits
                probs = F.softmax(logits, dim=-1)[0]
            p_ent, p_con, p_neu = float(probs[ent_i]), float(probs[con_i]), float(probs[neu_i])
            if p_con >= p_ent and p_con >= p_neu:
                c["accuracy"] = "contradicted"
                c["confidence"] = round(p_con, 4)
            elif p_ent >= p_neu:
                c["accuracy"] = "supported"
                c["confidence"] = round(p_ent, 4)
            else:
                c["accuracy"] = "unverified"
                c["confidence"] = round(max(p_neu, p_ent), 4)
            c["evidence_grade"] = "L4"
            c["epistemic_status"] = c["accuracy"]
            c["reasoning"] = (f"mDeBERTa-XNLI 判定：entail={p_ent:.2f} "
                              f"contra={p_con:.2f} neutral={p_neu:.2f}")
        return True
    except Exception as e:
        logger.warning("Layer2 推理失败，降级 unverified：%s", e)
        for c in targets:
            if c.get("accuracy") != "contradicted":
                c["accuracy"] = "unverified"
                c["confidence"] = 0.0
        return False
