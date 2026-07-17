"""v0.4.2 确定性层 + 缓存稳定性测试（不烧 key，mock LLM）。

验证：
  CE0  build_skeleton 产出 Top-K（显著度降序 + 7 维信号标签，零 LLM、确定性）
  CE1+CE2 extract_claims_self_consistent 在 N 次 mock 返回下组合频率门槛并集
          （普通主张需 ≥⌈N/2⌉ 次出现；高风险/高置信主张豁免保留）
  CE3  faithfulness_check 标记 grounded/ungrounded + anchor_ts（零 LLM）
  CE4  缓存落盘 → 重载 identical（claim_quotes 冻结，治"同视频三次不一样"）

运行：python tests/test_claim_stability.py
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.truth_track as tt
from core.salience import build_skeleton
from core.claim_cache import load_claim_cache, save_claim_cache, cache_path

# 一段真实风格的字幕样本（B站教程口播）
SAMPLE_SUBS = [
    {"ts": "00:02", "start": 2.0, "end": 5.0, "text": "今天给大家讲一个新手怎么用酷家乐出图的方法"},
    {"ts": "00:08", "start": 8.0, "end": 11.0, "text": "首先你要打开酷家乐的户型工具"},
    {"ts": "00:20", "start": 20.0, "end": 25.0, "text": "很多人说零基础月入十万其实都是骗人的"},
    {"ts": "00:30", "start": 30.0, "end": 35.0, "text": "我做了一个账号三个月赚了五千块"},
    {"ts": "00:45", "start": 45.0, "end": 50.0, "text": "渲染的时候一定要把灯光打足"},
    {"ts": "01:00", "start": 60.0, "end": 66.0, "text": "这就是今天分享的全部内容大家记得点赞"},
]


def test_ce0_skeleton():
    sk = build_skeleton(SAMPLE_SUBS, top_k=12)
    assert sk, "skeleton 不应为空"
    assert len(sk) <= 12
    # v0.4.6 起：时间桶覆盖 → 骨架按时间排序（横跨全片），不再按显著度降序
    starts = [s.get("start", 0.0) for s in sk]
    assert starts == sorted(starts), "v0.4.6 后骨架应按时间升序（时间桶覆盖）"
    # 覆盖性：样本时间跨度 2~60s，骨架应横跨而非堆在片头
    assert starts[-1] - starts[0] >= 40.0, "骨架应横跨视频，不得堆在片头"
    for s in sk:
        assert "ts" in s and "text" in s and "signals" in s
        assert set(s["signals"]) >= {"pos", "dur", "rep", "rhet", "punct", "emo", "hook"}
        assert "bucket" in s, "v0.4.6 应标注 bucket（时间桶覆盖调试用）"
    print(f"[CE0] OK top_k={len(sk)} 时间跨度={starts[0]:.0f}~{starts[-1]:.0f}s 桶={[s['bucket'] for s in sk]}")
    return sk


def _mock_claims_responses():
    """模拟 N=3 次抽取：第1/3次返回 base，第2次多返回 extra（验证并集保留抽风漏的）。"""
    base = [
        {"claim_id": "c0", "quote": "很多人说零基础月入十万其实都是骗人的", "ts": "00:20",
         "factuality": "factual", "scope": "public", "check_worthy": True, "hedge_level": 0, "weasel_flag": False},
        {"quote": "我做了一个账号三个月赚了五千块", "ts": "00:30",
         "factuality": "personal", "scope": "personal", "check_worthy": False, "hedge_level": 0, "weasel_flag": False},
    ]
    extra = [
        {"quote": "渲染的时候一定要把灯光打足", "ts": "00:45",
         "factuality": "factual", "scope": "public", "check_worthy": True, "hedge_level": 0, "weasel_flag": False},
    ]
    return [{"claims": base}, {"claims": base + extra}, {"claims": base}]


def test_ce1_ce2_self_consistent(sk):
    responses = _mock_claims_responses()
    # 取 5 条骨架 → 每样本 1 页 → 3 次抽样正好对应 3 个 mock 响应（无多余调用）
    with mock.patch.object(tt, "call_llm_json", side_effect=responses):
        claims = tt.extract_claims_self_consistent(sk[:5], "测试视频", {}, n_samples=3)
    quotes = [c["quote"] for c in claims]
    assert len(claims) == 3, f"组合频率门槛并集后应得 3 条，实际 {len(claims)}: {quotes}"
    assert "渲染的时候一定要把灯光打足" in quotes, "第2次抽到的 extra（豁免：factual/public/check_worthy）应保留"
    print(f"[CE1+CE2] OK 并集={len(claims)} quotes={quotes}")


def test_ce1_ce2_frequency_threshold():
    """B：一次性非豁免噪声主张应被频率门槛滤掉（治漂移），豁免主张即使仅 1 次也留。"""
    base = [
        {"claim_id": "c0", "quote": "很多人说零基础月入十万其实都是骗人的", "ts": "00:20",
         "factuality": "factual", "scope": "public", "check_worthy": True,
         "hedge_level": 0, "weasel_flag": False},
    ]
    # noise：仅第2次出现，且非豁免（opinion + personal）
    noise = [
        {"quote": "我个人觉得这个软件界面挺好看的", "ts": "00:50",
         "factuality": "opinion", "scope": "personal", "check_worthy": False,
         "hedge_level": 0, "weasel_flag": False},
    ]
    # exempt_once：仅第2次出现，但命中豁免（factual/public/check_worthy）
    exempt_once = [
        {"quote": "正版软件请到官网下载", "ts": "00:55",
         "factuality": "factual", "scope": "public", "check_worthy": True,
         "hedge_level": 0, "weasel_flag": False},
    ]
    responses = [{"claims": base}, {"claims": base + noise + exempt_once}, {"claims": base}]
    with mock.patch.object(tt, "call_llm_json", side_effect=responses):
        claims = tt.extract_claims_self_consistent(SAMPLE_SUBS[:5], "测试视频", {}, n_samples=3)
    quotes = [c["quote"] for c in claims]
    assert "很多人说零基础月入十万其实都是骗人的" in quotes, "稳定主张(3/3)必留"
    assert "正版软件请到官网下载" in quotes, "豁免主张(仅1次)也应保留"
    assert "我个人觉得这个软件界面挺好看的" not in quotes, "一次性非豁免噪声应被频率门槛滤掉"
    print(f"[CE1+CE2-B] OK 滤掉噪声1条、豁免保留1条，最终 {len(claims)} 条")


def test_ce3_faithfulness():
    claims = [
        {"claim_id": "c0", "quote": "很多人说零基础月入十万其实都是骗人的", "ts": "00:20"},
        {"claim_id": "c1", "quote": "这条视频里根本没有出现的虚构主张xyz", "ts": ""},
    ]
    kept, dropped = tt.faithfulness_check(claims, SAMPLE_SUBS)
    # v0.4.6 起 CE3 只标记不硬删：幻影标 ungrounded，最终去留交 guard NLI 裁决
    assert dropped == 1, f"应标记 1 条幻影为 ungrounded，实际 {dropped}"
    assert kept[0]["faithfulness"] == "grounded"
    assert kept[0]["anchor_ts"] == "00:20"
    assert kept[1]["faithfulness"] == "ungrounded", "幻影主张应被标记而非静默删除"
    assert len(kept) == 2, "CE3 不再硬删，返回全部主张（含 ungrounded）"
    print(f"[CE3] OK kept={len(kept)} ungrounded={dropped} anchor={kept[0]['anchor_ts']}")


def test_guard_fallback_to_ce3():
    # #143：guard 响应截断漏覆盖某 claim 时，回退 CE3 确定性判定，不默认放行也不误杀
    claims = [
        {"claim_id": "c0", "quote": "很多人说零基础月入十万其实都是骗人的",
         "ts": "00:20", "faithfulness": "grounded", "anchor_ts": "00:20"},
        {"claim_id": "c1", "quote": "这条视频里根本没有出现的虚构主张xyz",
         "ts": "", "faithfulness": "ungrounded", "anchor_ts": ""},
    ]
    # guard 只返回了 c0（c1 被截断漏掉）→ 应回退 CE3：c0 grounded 留、c1 ungrounded 删
    sup = {"results": [{"claim_id": "c0", "supported": True}]}
    with mock.patch.object(tt, "call_llm_json", return_value=sup):
        kept, dropped = tt.guard_claim_faithfulness(claims, SAMPLE_SUBS, {})
    assert dropped == 1, f"漏覆盖的 ungrounded 主张应被回退判定删除，实际 dropped={dropped}"
    assert len(kept) == 1 and kept[0]["claim_id"] == "c0"
    assert kept[0]["faithfulness"] == "grounded"
    print(f"[GUARD] OK kept={len(kept)} dropped={dropped}（截断漏覆盖→回退CE3）")


def test_guard_fallback_keeps_ce3_grounded():
    # 反向：guard 漏覆盖一条 CE3 grounded 的主张 → 应保留（不误杀）
    claims = [
        {"claim_id": "c0", "quote": "很多人说零基础月入十万其实都是骗人的",
         "ts": "00:20", "faithfulness": "grounded", "anchor_ts": "00:20"},
        {"claim_id": "c1", "quote": "渲染的时候一定要把灯光打足",
         "ts": "00:40", "faithfulness": "grounded", "anchor_ts": "00:40"},
    ]
    sup = {"results": [{"claim_id": "c0", "supported": True}]}  # c1 漏覆盖
    with mock.patch.object(tt, "call_llm_json", return_value=sup):
        kept, dropped = tt.guard_claim_faithfulness(claims, SAMPLE_SUBS, {})
    assert dropped == 0, f"漏覆盖的 CE3 grounded 主张应保留，实际 dropped={dropped}"
    assert len(kept) == 2
    print(f"[GUARD2] OK kept={len(kept)} dropped={dropped}（漏覆盖grounded→保留）")


def test_ce4_cache():
    vid = "TEST_BV_CACHE"
    p = cache_path(vid)
    if p.exists():
        p.unlink()
    claims = [
        {"claim_id": "c0", "quote": "q1", "ts": "00:20", "faithfulness": "grounded", "anchor_ts": "00:20"},
        {"claim_id": "c1", "quote": "q2", "ts": "00:30", "faithfulness": "grounded", "anchor_ts": "00:30"},
    ]
    # v0.4.7 起缓存需带 verify_sig 才命中（版本化失效：无 sig = 过期）
    sig = "test_sig_v049"
    assert save_claim_cache(vid, claims, verify_sig=sig)
    loaded = load_claim_cache(vid, verify_sig=sig)
    assert loaded is not None, "带 sig 的缓存应命中"
    assert [c["quote"] for c in loaded["claims"]] == [c["quote"] for c in claims], "缓存重载应一致"
    # 版本化失效：sig 不符视为未命中（旧缓存不掩盖新模型/逻辑）
    assert load_claim_cache(vid, verify_sig="different_sig") is None, "sig 不符应失效"
    print(f"[CE4] OK cache identical, n={len(loaded['claims'])}")
    if p.exists():
        p.unlink()


def test_norm_quote_dedup_context_prefix():
    """v0.4.9 回归：LLM 把骨架「上下文：…」装饰原样带回 quote 时，同源变体须正确归一化。

    复现 RUN1 真实重复：三条变体修复前应得三个不同 key（漏去重）；
    修复后①+②合并同键、③剥掉「上下文：…」装饰块。
    """
    a = "一家店铺 / 短短一个月的下单人数"
    b = "一家店铺 短短一个月的下单人数"
    c = "一家店铺  「上下文：直接就卖到上千甚至上万 / 一家店铺 / 短短一个月的下单人数」"
    ka, kb, kc = tt._norm_quote(a), tt._norm_quote(b), tt._norm_quote(c)
    assert ka == kb, f"纯文本/分隔符变体应同键，实得 {ka!r} vs {kb!r}"
    assert "上下文" not in kc, f"上下文装饰应被剥除，实得 {kc!r}"
    print(f"[norm] OK 去重键 a==b={ka!r}, c={kc!r}")


if __name__ == "__main__":
    sk = test_ce0_skeleton()
    test_ce1_ce2_self_consistent(sk)
    test_ce1_ce2_frequency_threshold()
    test_ce3_faithfulness()
    test_guard_fallback_to_ce3()
    test_guard_fallback_keeps_ce3_grounded()
    test_ce4_cache()
    test_norm_quote_dedup_context_prefix()
    print("\nALL TESTS PASSED")
