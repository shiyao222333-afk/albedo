"""临时验证 AF1 验证级别 + AF2 两分数对齐（跑完即删）。"""
from core.judgment import judge_document
from core.report import _render_verdict_card

# MiniCheck 本地字幕核验支持，但无联网核查(web_status 非 verified) → self_consistent
c_mini = [{"quote": "x", "ts": "00:10", "factuality": "factual", "scope": "public",
           "check_worthy": True, "accuracy": "supported", "web_status": "",
           "red_flags": [], "hedge_level": 0, "weasel_flag": False}]
v_mini = judge_document(c_mini, persuasion_polish=0.0)
print("MiniCheck核验(无联网):", v_mini.truth_label, v_mini.verification_level)
assert v_mini.truth_label == "true"
assert v_mini.verification_level == "self_consistent", "MiniCheck 本地核验≠外部已验证"

# 联网核查确认(web_status=verified) → externally_verified
c_web = [{"quote": "x", "ts": "00:10", "factuality": "factual", "scope": "public",
          "check_worthy": True, "accuracy": "supported", "web_status": "verified",
          "red_flags": [], "hedge_level": 0, "weasel_flag": False}]
v_web = judge_document(c_web, persuasion_polish=0.0)
print("联网核查确认:", v_web.truth_label, v_web.verification_level)
assert v_web.verification_level == "externally_verified"
print("AF1 验证级别区分 OK（MiniCheck本地 / 联网外部）")

# AF2 报告：真实 + self_consistent → 声明"视频自洽·待外部核实"
out = {
    "quality": {"truthfulness": {"label": "true", "score": 98,
                                  "evidence_grade": "L4", "verification_level": "self_consistent"}},
    "status": "accepted",
    "trust_score": 0.6,
    "form_score": 0.9,
    "content_type": "tutorial",
    "content_extract": {"kind": "sop", "steps": [{"text": "a", "ts": "00:01"}],
                        "preconditions": [], "warnings": [], "completion_checklist": [],
                        "_gate": {"checked": 1, "dropped": 0, "reasons": []},
                        "_meta": {"intent": ["教学"], "monetization": False}},
    "summary": {"gist": "教做图", "bullets": ["a"]},
    "monetization": {},
}
card = _render_verdict_card(out)
print("---- 结论卡 ----")
print(card)
assert "真实（视频自洽·待外部核实）" in card, "AF1 声明缺失"
assert "自洽置信 0.98" in card, "AF2 自洽置信未对齐"
assert "入库信任分（FPF）：0.6（单源未联网深验，仅供参考）" in card, "AF2 FPF 标注缺失"
assert "｜ 可信度 0.6 ｜" not in card, "旧冲突标签仍在"
print("AF2 两分数对齐 OK")
print("\nALL AF TESTS PASSED")
