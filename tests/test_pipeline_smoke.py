"""v0.4.2 验真编排(A5e)冒烟测试（mock LLM，不烧 key）。

直接验证 _run_truth_track 的 CE0→CE4 接入：
  - 缓存命中：预置 cache → 直接载入，不再调 LLM 抽取（claim_quotes 冻结）
  - 抽取并写缓存：无 cache → 跑 CE1+CE2 抽取 → CE3 自检 → 写 cache
同时验证 Layer3 联网核查在无 key 时诚实降级（web_status=pending）。
"""
from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.truth_track as tt
from core.claim_cache import load_claim_cache, save_claim_cache, cache_path

SAMPLE_SUBS = [
    {"ts": "00:02", "start": 2.0, "end": 5.0, "text": "今天给大家讲一个新手怎么用酷家乐出图的方法"},
    {"ts": "00:08", "start": 8.0, "end": 11.0, "text": "首先你要打开酷家乐的户型工具"},
    {"ts": "00:20", "start": 20.0, "end": 25.0, "text": "很多人说零基础月入十万其实都是骗人的"},
    {"ts": "00:30", "start": 30.0, "end": 35.0, "text": "我做了一个账号三个月赚了五千块"},
    {"ts": "00:45", "start": 45.0, "end": 50.0, "text": "渲染的时候一定要把灯光打足"},
    {"ts": "01:00", "start": 60.0, "end": 66.0, "text": "这就是今天分享的全部内容大家记得点赞"},
]
CACHED_QUOTE = "很多人说零基础月入十万其实都是骗人的"


class _Inp:
    title = "测试视频"
    danmaku = []


def _fake_verify_claims(claims, llm_kwargs=None, subtitle_lines=None):
    for c in claims:
        if c.get("accuracy") == "contradicted":
            continue
        c["accuracy"] = "unverified"
        c["confidence"] = 0.0
        c["epistemic_status"] = "unverified"
        if not c.get("reasoning"):
            c["reasoning"] = "Layer2 未部署，标 unverified"


def test_cache_hit():
    vid = "TEST_BV_HIT"
    p = cache_path(vid)
    if p.exists():
        p.unlink()
    cached = [{
        "claim_id": "c0", "quote": CACHED_QUOTE, "ts": "00:20", "faithfulness": "grounded",
        "anchor_ts": "00:20", "factuality": "factual", "scope": "public", "check_worthy": True,
        "hedge_level": 0, "weasel_flag": False, "accuracy": "unverified", "red_flags": [],
        "contradicts_with": [], "validity_class": "", "verified_date": "", "confidence": 0.0,
        "epistemic_status": "", "evidence": "", "reasoning": "", "is_visual_claim": False,
        "cross_modal_contradiction": False, "creator_id": "", "creator_rep_delta": 0.0,
        "web_status": "pending",
    }]
    save_claim_cache(vid, cached)
    with mock.patch.object(tt, "call_llm_json", side_effect=RuntimeError("no key")), \
         mock.patch.object(tt, "verify_claims_web", _fake_verify_claims):
        res = tt._run_truth_track(_Inp(), subtitle_lines=SAMPLE_SUBS, clean_text="",
                                  llm_kwargs={}, video_id=vid, cache_enabled=True)
    assert res["claims"], "缓存命中应有主张"
    assert res["claims"][0]["quote"] == CACHED_QUOTE
    # Layer3 无 key → pending
    assert res["claims"][0]["web_status"] == "pending", "Layer3 无 key 应诚实降级 pending"
    print(f"[A5e cache-hit] OK claims={len(res['claims'])} web_status={res['claims'][0]['web_status']}")
    if p.exists():
        p.unlink()


def test_extract_and_cache():
    vid = "TEST_BV_EXTRACT"
    p = cache_path(vid)
    if p.exists():
        p.unlink()
    fake = {"claims": [
        {"quote": CACHED_QUOTE, "ts": "00:20", "factuality": "factual", "scope": "public",
         "check_worthy": True, "hedge_level": 0, "weasel_flag": False},
    ]}
    with mock.patch.object(tt, "call_llm_json", return_value=fake), \
         mock.patch.object(tt, "verify_claims_web", _fake_verify_claims):
        res = tt._run_truth_track(_Inp(), subtitle_lines=SAMPLE_SUBS, clean_text="",
                                  llm_kwargs={}, video_id=vid, cache_enabled=True)
    assert res["claims"], "应抽到主张"
    # 缓存应写入（CE4）
    loaded = load_claim_cache(vid)
    assert loaded is not None, "应写缓存"
    assert loaded["claims"][0]["quote"] == CACHED_QUOTE
    # CE3 忠实性：quote 出自字幕 → grounded + anchor_ts
    assert res["claims"][0]["faithfulness"] == "grounded"
    assert res["claims"][0]["anchor_ts"] == "00:20"
    print(f"[A5e extract+cache] OK extracted={len(res['claims'])} cached=yes anchor={res['claims'][0]['anchor_ts']}")
    if p.exists():
        p.unlink()


if __name__ == "__main__":
    test_cache_hit()
    test_extract_and_cache()
    print("\nALL SMOKE TESTS PASSED")
