"""Albedo (Lian Zhen) · 验真环节流水线 (v0.3.0)

验真 = 把视频里的"断言"一条条揪出来，分别判断真假/可疑，而非只给整条视频一个总分。
对应研究 docs/RESEARCH-TRUTH-VERIFICATION-V2 / -V3。

分层（用户拍板）：
  Layer 0.5 (防坑, 不联网): 抽断言后做忠实度核查 —— 每条抽取断言拿字幕原文 NLI 一遍，
               LLM 瞎编的(视频没说的话)直接丢弃，否则它会披着"已核查"外衣骗人（V3 遗漏3，最危险）。
  Layer 1 (不联网快筛): 话术识别(绝对化骗局/水词/模糊语) + 自相矛盾(两两 NLI) +
               时效标记(verified_date + validity_class) + 事实观点/个人公开分类（V2 三维度）。
  Layer 2 (联网深验, MiniCheck 本地): 抽证据→MiniCheck 逐条验 supported/contradicted。
               沙箱/未部署 MiniCheck → 全部标 unverified（保守，V3 遗漏5），接口留好待本机启用。

OCR 跨模态、UP 主跨视频信用累积：按用户指示列入路线图，本期仅定义字段、不实现逻辑。

设计铁律（沿用内容线）：
  - 确定性：call_llm_json temperature=0 + 固定 JSON schema 枚举
  - 全程 try/except 包裹每步，失败→安全默认续跑，绝不整条中断
  - 抽取断言锚定 key_sentences（真实字幕原话），从源头降低瞎编风险
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from core.llm import call_llm_json
from core.form_track import apply_rhetoric_rules, _norm_cn  # 修辞规则库单一来源（v0.4.0 迁至形式线）

# Layer2 未部署说明（沙箱标 unverified 时记录的口径）
LAYER2_NOTE = "Layer2 联网深验(MiniCheck 本地)未部署，本轮标 unverified；本机部署后启用逐条验真。"


# ───────────────────────────────────────────────────────────────────────────
# 规则库：时效（Layer1c）；修辞规则已迁至 core.form_track（单一来源，truth_track 消费）
# ───────────────────────────────────────────────────────────────────────────
# 时效关键词（命中→timeboxed 限时）
_TIMEBOXED_KW = re.compile(
    r"(规则|规定|政策|法规|平台|算法|机制|制度|条款|公约)"
    r"|(价格|费用|收费|票价|费率|佣金|定价|售价|报价|定金|首付)"
    r"|(版本|更新|改版|升级|新版|v\d|改版|迭代)"
    r"|(门槛|限额|限制|上限|下限|配额|封顶|底线)"
    r"|(20\d\d年|今年|现在|目前|最新|当前|截至)"
)


def _ts_to_sec(ts: str) -> float:
    """'03:21' → 201.0；解析失败返回 0.0。"""
    if not ts:
        return 0.0
    m = re.match(r"(\d{1,2}):(\d{2})", ts)
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + int(m.group(2))


# ───────────────────────────────────────────────────────────────────────────
# Layer 0: 抽取原子断言（锚定 key_sentences 真实原话）
# ───────────────────────────────────────────────────────────────────────────
_CLAIM_SYSTEM = """你是验真断言抽取器，隶属于「炼真(Albedo)」流水线。
任务：从给定「关键原话」中抽取原子断言（每条独立、可验证的小主张）。

规则：
1. 每条断言必须锚定到一条「关键原话」——quote 取原话原文（可微调措辞，但不得添加原话里没有的事实）。
2. 若一条原话含多个独立主张，拆成多条断言。
3. 判断每条：
   - factuality: factual(可证伪事实) / opinion(主观价值判断) / mixed(前半事实后半观点)
   - scope: personal(第一人称经验"我试了…") / public(可外部验证的公开断言)
   - check_worthy: 是否"可证伪的事实主张"（personal/opinion 多为 False，public+factual 为 True）
   - hedge_level: 0(绝对,无保留) / 1(弱保留,如"比较""往往") / 2(强模糊,如"可能""大概""据说")
   - weasel_flag: 是否含水词（"研究表明""专家说""大多数人同意"等无具体出处的权威暗示）

只输出 JSON（不要解释）：
{
  "claims": [
    {"claim_id":"c0","quote":"<原话>","ts":"mm:ss","factuality":"factual|opinion|mixed",
     "scope":"personal|public","check_worthy":true/false,"hedge_level":0,"weasel_flag":false},
    ...
  ]
}"""


def extract_claims(source_items: list, title: str, llm_kwargs: dict = None) -> list:
    """从关键原话抽取原子断言。

    source_items: list[{ts, text}]（内容线传 key_sentences；通用路径传 clean_text 切句）。
    返回 list[dict]（ClaimVerification 字段子集，含 claim_id/quote/ts/factuality/scope/...）。
    失败降级 → []（不阻断主流程）。
    """
    items = [s for s in (source_items or []) if isinstance(s, dict) and s.get("text")]
    if not items:
        return []
    src_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in items[:40])
    user = f"视频标题：{title}\n\n关键原话：\n{src_text}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _CLAIM_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=2000,
            **(llm_kwargs or {}),
        )
        raw = data.get("claims") or []
        claims = []
        for i, c in enumerate(raw):
            if not isinstance(c, dict):
                continue
            quote = (c.get("quote") or "").strip()
            if not quote:
                continue
            ts = (c.get("ts") or "").strip()
            claims.append({
                "claim_id": c.get("claim_id") or f"c{i}",
                "quote": quote,
                "ts": ts,
                "start": _ts_to_sec(ts),
                "factuality": _coerce(c.get("factuality"), ("factual", "opinion", "mixed"), "factual"),
                "scope": _coerce(c.get("scope"), ("personal", "public"), "public"),
                "check_worthy": bool(c.get("check_worthy", False)),
                "hedge_level": _int(c.get("hedge_level"), 0),
                "weasel_flag": bool(c.get("weasel_flag", False)),
                "faithfulness": "grounded",
                "accuracy": "",
                "red_flags": [],
                "contradicts_with": [],
                "validity_class": "",
                "verified_date": "",
                "confidence": 0.0,
                "epistemic_status": "",
                "evidence": "",
                "reasoning": "",
                "is_visual_claim": False,
                "cross_modal_contradiction": False,
                "creator_id": "",
                "creator_rep_delta": 0.0,
            })
        return claims
    except Exception:
        return []


# ───────────────────────────────────────────────────────────────────────────
# Layer 0.5: 断言忠实度核查（防 LLM 瞎编）—— 最关键防坑层（V3 遗漏3）
# ───────────────────────────────────────────────────────────────────────────
_GUARD_SYSTEM = """你是断言忠实性检查器。给定一组"抽取断言"和"视频字幕原文"，
对每条断言判断：它陈述的内容是否能被字幕原文直接支撑（蕴含）？
- supported=true：字幕里有对应内容，或可由字幕合理推出
- supported=false：字幕里找不到任何依据，疑似抽取器编造/臆测（应丢弃）

只输出 JSON（不要解释）：
{
  "results": [
    {"claim_id":"c0","supported":true/false},
    ...
  ]
}"""


def guard_claim_faithfulness(claims: list, subtitle_lines: list, llm_kwargs: dict = None):
    """Layer 0.5：每条抽取断言 vs 字幕原文 NLI，ungrounded 的直接丢弃（防污染）。

    无字幕（通用路径）→ 无法核查，全部保留（faithfulness 保持 grounded 默认）。
    返回 (kept_claims, n_dropped)。LLM 失败 → 全部保留（降级不丢数据）。
    """
    claims = claims or []
    if not claims:
        return [], 0
    subs = subtitle_lines or []
    if not subs:
        return claims, 0  # 无原文可查，保留

    subs_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subs)
    claims_text = "\n".join(f"{c['claim_id']}: {c['quote']}" for c in claims)
    user = f"字幕原文：\n{subs_text}\n\n待核查断言：\n{claims_text}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _GUARD_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=2000,
            **(llm_kwargs or {}),
        )
        sup_map = {r.get("claim_id"): bool(r.get("supported", True))
                   for r in (data.get("results") or [])}
        kept, dropped = [], 0
        for c in claims:
            if sup_map.get(c["claim_id"], True):
                kept.append(c)
            else:
                c["faithfulness"] = "ungrounded"
                dropped += 1  # 丢弃（不进入后续验真，避免披"已核查"外衣）
        return kept, dropped
    except Exception:
        return claims, 0  # 降级：保留全部


# ───────────────────────────────────────────────────────────────────────────
# Layer 1a: 话术识别（规则，不联网）：绝对化骗局话术 + 水词 + 模糊语（V3 遗漏6）
# ───────────────────────────────────────────────────────────────────────────
def detect_rhetoric(claims: list, clean_text: str = "") -> list:
    """规则识别每条断言的话术特征（消费形式线单一来源规则库 apply_rhetoric_rules）。

    就地写入 red_flags / weasel_flag / hedge_level。返回全局命中的 red_flags 标签集合（去重）。
    v0.4.0 起：修辞规则正则统一归 core.form_track，此处仅消费，避免重复维护。
    """
    claims = claims or []
    blob = clean_text or ""
    global_flags = set()
    for c in claims:
        red_flags, weasel, lvl = apply_rhetoric_rules(c.get("quote", ""), blob)
        c["red_flags"] = red_flags
        global_flags.update(red_flags)
        if weasel:
            c["weasel_flag"] = True
        c["hedge_level"] = max(c.get("hedge_level", 0) or 0, lvl)
    return sorted(global_flags)


# ───────────────────────────────────────────────────────────────────────────
# Layer 1b: 自相矛盾检测（两两 NLI，逻辑必然不实，不联网）（V3 遗漏1）
# ───────────────────────────────────────────────────────────────────────────
_SC_SYSTEM = """你是逻辑矛盾检测器。给定一组断言（带 id 与原文），
找出哪些「对」互相矛盾——即两句话不能同时为真（例如一个说免费、另一个说收费；
一个说日入过万、另一个说根本没赚到）。

只输出 JSON（不要解释）：
{
  "contradictions": [
    {"a_id":"c0","b_id":"c1","explanation":"一句话说明矛盾点"}
  ]
}
若无矛盾，返回 {"contradictions":[]}。"""


def detect_self_contradiction(claims: list, llm_kwargs: dict = None) -> list:
    """两两 NLI 检测自相矛盾，就地写 claim.contradicts_with + accuracy=contradicted。
    返回矛盾对列表（供报告）。失败降级 → []。
    """
    claims = claims or []
    if len(claims) < 2:
        return []
    claims_text = "\n".join(f"{c['claim_id']}: {c['quote']}" for c in claims)
    user = f"断言列表：\n{claims_text}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _SC_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=2000,
            **(llm_kwargs or {}),
        )
        pairs = data.get("contradictions") or []
        by_id = {c["claim_id"]: c for c in claims}
        out = []
        for p in pairs:
            aid, bid = p.get("a_id"), p.get("b_id")
            if aid not in by_id or bid not in by_id or aid == bid:
                continue
            a, b = by_id[aid], by_id[bid]
            a["contradicts_with"].append({"claim_id": bid, "ts": b.get("ts", "")})
            b["contradicts_with"].append({"claim_id": aid, "ts": a.get("ts", "")})
            a["accuracy"] = "contradicted"
            b["accuracy"] = "contradicted"
            a["reasoning"] = p.get("explanation", "视频自相矛盾")
            b["reasoning"] = p.get("explanation", "视频自相矛盾")
            out.append({"a_id": aid, "a_ts": a.get("ts", ""),
                        "b_id": bid, "b_ts": b.get("ts", ""),
                        "explanation": p.get("explanation", "")})
        return out
    except Exception:
        return []


# ───────────────────────────────────────────────────────────────────────────
# Layer 1c: 时效标记（规则，不联网）：verified_date + validity_class（V3 遗漏2）
# ───────────────────────────────────────────────────────────────────────────
def tag_recency(claims: list, verified_date: str = None) -> None:
    """就地写 verified_date（今日）+ validity_class（命中限时关键词→timeboxed，默认 evergreen）。"""
    vd = verified_date or date.today().isoformat()
    for c in (claims or []):
        c["verified_date"] = vd
        c["validity_class"] = "timeboxed" if _TIMEBOXED_KW.search(c.get("quote", "")) else "evergreen"


# ───────────────────────────────────────────────────────────────────────────
# Layer 2: 联网深验（MiniCheck 本地）—— 接口留好，沙箱标 unverified（V3 遗漏5 保守）
# ───────────────────────────────────────────────────────────────────────────
def verify_claims_web(claims: list, llm_kwargs: dict = None) -> None:
    """Layer 2 逐条验真（MiniCheck 本地部署后启用）。

    当前沙箱/未部署 MiniCheck → 全部标 unverified（保守，绝不臆断为真），不实际跑。
    真实启用：对 check_worthy 且 scope=public 且 factuality=factual 的断言，
    抽证据 → MiniCheck 逐条判 supported/contradicted → 写 accuracy/evidence_grade/confidence。
    已判定 contradicted（Layer1b 自相矛盾）的断言跳过，保留矛盾结论。
    """
    for c in (claims or []):
        if c.get("accuracy") == "contradicted":
            continue  # 自相矛盾已定论，不被 unverified 覆盖
        c["accuracy"] = "unverified"
        c["confidence"] = 0.0
        c["epistemic_status"] = "unverified"
        if not c.get("reasoning"):
            c["reasoning"] = LAYER2_NOTE


# ───────────────────────────────────────────────────────────────────────────
# 聚合：文档级结论（落熔知字段 + 报告）
# ───────────────────────────────────────────────────────────────────────────
def aggregate(claims: list, dropped_count: int = 0, persuasion_polish: float = 0.0) -> dict:
    """聚合逐条结果为文档级摘要。

    信任分(0-1)保守：未验证不过高（V3 遗漏5）。矛盾→0.3，话术→0.4，
    全观点/个人→0.55，其余→0.5；上限 0.6。
    severity: alert(矛盾) / warn(话术) / ok。
    persuasion_polish(G1 反向桥)：高说服包装 + 证据未验证 → 额外谨慎（轻微下调信任）。
    """
    claims = claims or []
    n = len(claims)
    n_contradicted = sum(1 for c in claims if c.get("accuracy") == "contradicted")
    n_redflag = sum(1 for c in claims if c.get("red_flags"))
    n_timeboxed = sum(1 for c in claims if c.get("validity_class") == "timeboxed")
    is_personal = any(c.get("scope") == "personal" for c in claims)
    has_factual_public = any(
        c.get("factuality") == "factual" and c.get("scope") == "public" for c in claims
    )

    if n_contradicted > 0:
        severity = "alert"
        trust = 0.3
        epistemic_status = "unverified"
    elif n_redflag > 0:
        severity = "warn"
        trust = 0.4
        epistemic_status = "unverified"
    elif not has_factual_public:
        severity = "ok"
        trust = 0.55  # 个人经验/观点不可验但不假，略高于基线
        epistemic_status = "unverified"
    else:
        severity = "ok"
        trust = 0.5
        epistemic_status = "unverified"

    # G1 反向桥：高说服包装 + 未验证证据 → 额外谨慎（真相错觉防御）
    polish_note = ""
    if persuasion_polish >= 0.7 and severity == "ok":
        trust = max(0.2, round(trust * 0.85, 2))
        polish_note = "高说服包装 + 证据未验证，已额外下调信任（真相错觉防御）"

    contradictions = []
    for c in claims:
        for other in c.get("contradicts_with", []):
            contradictions.append({
                "claim_id": c.get("claim_id"), "ts": c.get("ts"),
                "with_claim_id": other.get("claim_id"), "with_ts": other.get("ts"),
            })

    recency_note = (
        "含限时断言（平台规则/价格/版本类），结论有时效，建议复核后谨慎采用。"
        if n_timeboxed else ""
    )
    if polish_note:
        recency_note = (recency_note + "；" if recency_note else "") + polish_note

    return {
        "n_claims": n,
        "n_dropped": dropped_count,
        "n_contradicted": n_contradicted,
        "n_redflag": n_redflag,
        "n_timeboxed": n_timeboxed,
        "is_personal": is_personal,
        "severity": severity,
        "trust_score": trust,
        "epistemic_status": epistemic_status,
        "contradictions": contradictions,
        "recency_note": recency_note,
        "persuasion_polish": persuasion_polish,
        "red_flags": sorted({f for c in claims for f in c.get("red_flags", [])}),
    }


# ───────────────────────────────────────────────────────────────────────────
# 编排入口
# ───────────────────────────────────────────────────────────────────────────
def _run_truth_track(
    inp,
    *,
    key_sentences: list = None,
    subtitle_lines: list = None,
    clean_text: str = "",
    llm_kwargs: dict = None,
    persuasion_polish: float = 0.0,
) -> dict:
    """验真主流程（内容线/通用路径共用）。

    参数：
      key_sentences: 内容线关键原话 [{ts, text}]（锚定抽取源；空则退化为 clean_text 切句）
      subtitle_lines: 字幕原文（Layer0.5 核查用；通用路径为空→跳过核查）
      clean_text: 净化后全文（话术规则 + 通用路径兜底抽取）
      persuasion_polish: 形式线 G1 反向桥（高包装+未验证证据→额外谨慎）
    返回 {claims: list[dict], truth_track: dict, dropped: int}。整体不抛。
    """
    key_sentences = key_sentences or []
    subtitle_lines = subtitle_lines or []

    # 抽取源：优先关键原话；否则 clean_text 切句（无 ts）
    if key_sentences:
        source_items = [{"ts": k.get("ts", ""), "text": k.get("text", "")} for k in key_sentences]
    else:
        source_items = [{"ts": "", "text": s.strip()}
                         for s in re.split(r"[。！？\n]+", clean_text or "") if s.strip()][:20]

    claims = extract_claims(source_items, getattr(inp, "title", "") or "", llm_kwargs)
    kept, dropped = guard_claim_faithfulness(claims, subtitle_lines, llm_kwargs)
    detect_rhetoric(kept, clean_text)
    detect_self_contradiction(kept, llm_kwargs)
    tag_recency(kept)
    verify_claims_web(kept, llm_kwargs)  # Layer2 当前标 unverified
    truth_track = aggregate(kept, dropped, persuasion_polish=persuasion_polish)
    return {"claims": kept, "truth_track": truth_track, "dropped": dropped}


# ── 小工具 ──
def _coerce(v, allowed, default):
    v = (v or "").strip().lower()
    return v if v in allowed else default


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default
