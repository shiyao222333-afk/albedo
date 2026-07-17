"""v0.4.9 F 任务：被过滤主张审计留痕验证。

不依赖 LLM / 网络：用 unittest.mock 替换抽取与验真环节，
断言 _run_truth_track 在所有硬删过滤器上都能产出带原因/阶段的审计条目，
且真主张不被误杀进审计。
"""
import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock
import core.truth_track as tt


# ── 合成主张集：覆盖 水词 / 非可证伪观点 / 真事实(字幕有依据) / 真事实(字幕无依据) ──
def _mk_claims():
    return [
        # 水词/过渡句（应 AE1_water 剔除）
        {"claim_id": "c0", "quote": "接下来全程都是干货", "ts": "00:10", "check_worthy": False},
        # 非可证伪观点（应 AE1_noncheckworthy 剔除）
        {"claim_id": "c1", "quote": "我觉得这个项目冷启动最难", "ts": "00:20", "check_worthy": False},
        # 真事实 + 字幕有依据（应保留）
        {"claim_id": "c2", "quote": "AI行业现在很火", "ts": "00:30", "check_worthy": True,
         "factuality": "factual", "scope": "public"},
        # 真事实 + 字幕无依据（应 Layer0.5 剔除）
        {"claim_id": "c3", "quote": "小红书运营核心是选题", "ts": "00:40", "check_worthy": True,
         "factuality": "factual", "scope": "public"},
    ]


def _fake_extract(*a, **k):
    return _mk_claims()


def _fake_guard(claims, subs, llm_kwargs=None):
    # 字幕里只有 c2 的内容 → c3 无依据被裁决丢弃
    subs_text = "\n".join(s.get("text", "") for s in (subs or []))
    kept = []
    for c in claims:
        if "AI行业" in c["quote"] and "很火" in c["quote"]:
            kept.append(c)
        elif c["claim_id"] == "c3":
            c["faithfulness"] = "ungrounded"
        else:
            kept.append(c)
    return kept, len(claims) - len(kept)


def test_dropped_audit():
    subs = [{"ts": "00:30", "text": "AI行业现在很火，机会很多"}]
    with mock.patch.object(tt, "extract_claims_self_consistent", _fake_extract), \
         mock.patch.object(tt, "extract_claims", _fake_extract), \
         mock.patch.object(tt, "guard_claim_faithfulness", _fake_guard), \
         mock.patch.object(tt, "detect_rhetoric", lambda *a, **k: None), \
         mock.patch.object(tt, "detect_self_contradiction", lambda *a, **k: None), \
         mock.patch.object(tt, "tag_recency", lambda *a, **k: None), \
         mock.patch.object(tt, "verify_claims_web", lambda *a, **k: None), \
         mock.patch.object(tt, "web_verify_claims", lambda *a, **k: None):
        out = tt._run_truth_track(
            types.SimpleNamespace(video_id="", title="", subtitle_lines=subs),
            key_sentences=[], subtitle_lines=subs, clean_text="",
            llm_kwargs={}, persuasion_polish=0.0,
            video_id="TEST_AUDIT", cache_enabled=False,
        )
    kept = out["claims"]
    audit = out["dropped_audit"]
    kept_quotes = {c["quote"] for c in kept}
    audit_stages = {a["stage"] for a in audit}

    # 1) 真事实 c2（字幕有依据）必须保留，且不能进审计
    assert "AI行业现在很火" in kept_quotes, "真主张 c2 被误杀"
    assert not any(a["quote"] == "AI行业现在很火" for a in audit), "c2 误入审计"

    # 2) 水词 c0 → AE1_water
    assert "AE1_water" in audit_stages, "水词未记入审计"
    assert any(a["quote"] == "接下来全程都是干货" and a["stage"] == "AE1_water" for a in audit)

    # 3) 观点 c1 → AE1_noncheckworthy
    assert "AE1_noncheckworthy" in audit_stages
    assert any(a["quote"] == "我觉得这个项目冷启动最难" and a["stage"] == "AE1_noncheckworthy" for a in audit)

    # 4) 字幕无依据 c3 → L0.5_ungrounded
    assert "L0.5_ungrounded" in audit_stages, "Layer0.5 剔除未记入审计"
    assert any(a["quote"] == "小红书运营核心是选题" and a["stage"] == "L0.5_ungrounded" for a in audit)

    # 5) 每条审计必须带 reason 与 ts
    for a in audit:
        assert a.get("reason"), f"审计条目缺 reason: {a}"
        assert "ts" in a, f"审计条目缺 ts: {a}"

    print(f"[AUDIT] OK kept={len(kept)} dropped_audit={len(audit)} stages={sorted(audit_stages)}")
    for a in audit:
        print(f"   - [{a['stage']}] {a['quote']} | ts={a['ts']} | {a['reason']}")


if __name__ == "__main__":
    import types
    test_dropped_audit()
