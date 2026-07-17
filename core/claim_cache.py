"""Albedo (Lian Zhen) · 主张缓存 (v0.4.2, CE4；v0.4.6 升级冻结范围；v0.4.7 版本化失效)

抽完的「最终主张集」落盘，复查/出报告直接读，不重抽也不重验 —— 从协议层冻结
"同视频三次不一样"的漂移。缓存内容 = 经 CE3 标记 + Layer0.5 guard 裁决 +
Layer1~Layer3 全部标记后的**最终主张集**（含 faithfulness/accuracy/red_flags/...），
缓存命中时跳过抽取与所有验真层，直接复现确定性结论。要强制重抽/重验用 cache_enabled=False。
键 = video_id（Nigredo 的 bvid，或测试脚本从文件名推导），文件 = cache/{video_id}.claims.json。

v0.4.7 关键修复（缓存科学解法）：
- **版本化失效（verify_sig）**：缓存里写入验真配置指纹（Layer2 模型名 + verify/judge 逻辑源码
  hash + LLM 模型名）。加载时若指纹不符 → 视为未命中、自动重算。这样换模型/改验真逻辑后
  **无需手动 rm 缓存**，旧缓存不再"掩盖"新模型（根治 2026-07-17 续9 的坑）。
- **保存顺序修正**：缓存必须在 Layer2 验真(verify_claims_web) + Layer3 之后才落盘，否则冻结的是
  "验真前"主张（accuracy 为空），命中缓存会丢掉真验真结论（根治 RUN1=true/RUN2=suspect 翻盘）。
- 旧格式（无 verify_sig 的缓存）一律视为失效，强制重算，保证安全。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def cache_path(video_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{video_id}.claims.json"


def load_claim_cache(video_id: str, verify_sig: str = ""):
    """命中返回 {"claims": list[dict], "form_track": dict|None}，未命中/失效/损坏返回 None。

    v0.4.6.1 起缓存同时冻结最终主张集与形式线(form_track / persuasion_polish)，
    使信任分聚合在复查时也完全确定性（避免 LLM 形式线方差导致 trust_score 微抖）。
    兼容 v0.4.6 及更早的「仅主张 list」旧缓存格式。

    v0.4.7 版本化失效：若缓存写入时的 verify_sig 与当前不符（或旧缓存无 sig），
    **视为未命中**返回 None —— 旧缓存不再掩盖新模型/新逻辑，无需手动 rm。
    """
    if not video_id:
        return None
    p = cache_path(video_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        # 旧格式：仅主张集，无 sig → 一律失效重算
        return None
    if isinstance(data, dict) and "claims" in data:
        stored_sig = data.get("verify_sig", "")
        if verify_sig and stored_sig and stored_sig != verify_sig:
            # 验真配置已变（换了模型/改了逻辑）→ 旧缓存失效
            return None
        if not stored_sig:
            # 旧格式无 sig → 失效重算（安全优先）
            return None
        data.setdefault("form_track", None)
        return data
    return None


def save_claim_cache(video_id: str, claims: list, form_track=None, verify_sig: str = "") -> bool:
    """冻结「最终主张集 + 形式线(form_track) + 验真配置指纹 verify_sig」。

    成功 True，失败 False（不阻断主流程）。

    注意调用时机：必须在 Layer2 验真(verify_claims_web) + Layer3 之后调用，
    否则冻结的是验真前主张（accuracy 空），命中缓存会丢真结论。
    form_track 含 persuasion_polish（G1 反向桥）等 LLM 产出；冻结后复查跳过 _run_form_track，
    信任分聚合不再受 LLM 方差影响（v0.4.6.1 修复 trust_score 微抖）。
    """
    if not video_id:
        return False
    try:
        p = cache_path(video_id)
        p.write_text(json.dumps(
            {"claims": claims, "form_track": form_track, "verify_sig": verify_sig},
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        return True
    except Exception:
        return False


def compute_verify_sig() -> str:
    """计算验真配置指纹：Layer2 模型名 + verify/judge 逻辑源码 hash + LLM 模型名。

    任一项变化 → 指纹变 → 旧缓存自动失效。这是"科学化解缓存复发"的核心。
    """
    parts = []
    try:
        from core import minicheck_verify as mv
        parts.append(getattr(mv, "MODEL_NAME", "?"))
        parts.append(hashlib.md5(inspect.getsource(mv).encode("utf-8", "ignore")).hexdigest()[:10])
    except Exception:
        parts.append("mv?")
    try:
        from core import judgment as jd
        parts.append(hashlib.md5(inspect.getsource(jd).encode("utf-8", "ignore")).hexdigest()[:10])
    except Exception:
        parts.append("jd?")
    parts.append(os.getenv("KB_LLM_MODEL", "default"))
    return hashlib.md5("|".join(parts).encode("utf-8", "ignore")).hexdigest()[:12]
