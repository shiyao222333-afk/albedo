"""Albedo (Lian Zhen) · 形式信号骨架 (v0.4.2, CE0)

确定性「显著度(salience)」打分：从字幕时间戳算出「哪些句是关键原话候选」，
作为抽主张(CE1)的约束骨架。全程不调 LLM（零成本、确定、<1s），治 DeepSeek 不稳。

信号（设计文档 §3.4，预设权重，#2 评测集后调）：
  w_pos   * pos_score        位置（前10秒/首句/总结段/结尾段高）
  w_dur   * duration_score    时长/停顿（长停顿后、语速突增）
  w_rep   * repetition_score  词频中心度 TF（重复=核心）
  w_rhet  * rhetoric_score    FT4 规则话术命中（绝对化/夸张加权更高）
  w_punct * punctuation_score ！？… 强调标点
  w_emo   * emotion_score     FT6 弹幕密度（weak，低权重）
  w_hook  * hook_score        前10秒钩子句

复用形式线单一来源规则库 apply_rhetoric_rules（core.form_track），不重复维护正则。
"""
from __future__ import annotations

import re
from collections import Counter

from core.form_track import apply_rhetoric_rules, _norm_cn

# ── 预设权重（设计文档 §3.4，权重和=1.0）──
W_POS = 0.22
W_DUR = 0.12
W_REP = 0.18
W_RHET = 0.20
W_PUNCT = 0.10
W_EMO = 0.06
W_HOOK = 0.12

# 强调标点（伪声学：无需音频即可从字幕推断情绪强调）
_PUNCT_RE = re.compile(r"[！？…!?]{1,}")

# 重复度统计时剔除的停用/标点字符（中英混合）
_STOP_CHARS = set(
    " ，。、！？；：" "''（）《》【】…—\n\r\t"
    "的 了 是 在 我 你 他 她 它 们 这 那 有 和 与 及 也 都 就 不 没 很 啊 吧 呢 吗 哦 嗯 啦 呀"
    " a an the of to and or is are was were be been in on at for with".split()
)


def _ts_to_sec(ts):
    if not ts:
        return 0.0
    m = re.match(r"(\d{1,2}):(\d{2})", ts or "")
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + int(m.group(2))


def _line_bounds(line: dict):
    """返回 (start_sec, end_sec, ts_str)，尽量从 start/end 或 ts 推导。"""
    start = line.get("start")
    end = line.get("end")
    ts = line.get("ts", "")
    if start is None and ts:
        start = _ts_to_sec(ts)
    if end is None and ts:
        end = start if start is not None else 0.0
    if start is None:
        start = 0.0
    if end is None or end < start:
        end = start + 2.0  # 默认一句约 2s
    return float(start), float(end), ts


def _char_freq(text: str) -> Counter:
    """字幕全文字符频率（剔除停用/标点）。"""
    norm = _norm_cn(text or "")
    cnt = Counter()
    for ch in norm:
        if ch in _STOP_CHARS or not ch.strip():
            continue
        cnt[ch] += 1
    return cnt


def build_skeleton(subtitle_lines, *, top_k: int = 12, clean_text: str = "", danmaku=None) -> list:
    """从字幕算形式信号骨架，返回 Top-K 候选关键原话（带时间戳+显著度+信号标签）。

    参数：
      subtitle_lines: list[{ts, start, end, text}]（Nigredo 解析字幕）
      top_k: 取显著度最高的前 K 句
      clean_text: 净化全文（FT4 规则兜底话术扫描用，可空）
      danmaku: list[{time, text}]（FT6 情绪弱代理，可空）
    返回 list[{rank, ts, text, salience, signals:{...}, flags:[...], context:[...]}]。
    确定性、零 LLM；无字幕 → []。
    """
    subs = [s for s in (subtitle_lines or [])
            if isinstance(s, dict) and (s.get("text") or "").strip()]
    if not subs:
        return []

    # 解析边界并排序
    bounds = []
    for s in subs:
        st, en, ts = _line_bounds(s)
        bounds.append({"start": st, "end": en, "ts": ts, "text": (s.get("text") or "").strip()})
    bounds.sort(key=lambda b: b["start"])
    n = len(bounds)
    if n == 0:
        return []

    video_dur = max(b["end"] for b in bounds)
    if video_dur <= 0:
        video_dur = 1.0

    # 全局伪声学：平均语速（chars/min）
    total_chars = sum(len(b["text"]) for b in bounds)
    avg_speech_rate = (total_chars / (video_dur / 60.0)) if video_dur > 0 else 0.0

    # 全局重复度：字符频率中心度
    char_counter = _char_freq("\n".join(b["text"] for b in bounds))
    max_c = max(char_counter.values()) if char_counter else 1

    # 弹幕密度分桶（30s 一桶），情绪弱代理
    danmaku_density = {}
    if danmaku:
        for d in danmaku:
            try:
                t = float(d.get("time") or 0)
            except (TypeError, ValueError):
                continue
            b = int(t // 30)
            danmaku_density[b] = danmaku_density.get(b, 0) + 1
    max_danmaku = max(danmaku_density.values()) if danmaku_density else 1

    results = []
    for i, b in enumerate(bounds):
        text = b["text"]
        start, end = b["start"], b["end"]
        dur = max(end - start, 0.1)
        gap_before = start - bounds[i - 1]["end"] if i > 0 else start

        # 1) 位置显著度
        if start <= 10.0:
            pos = 1.0                       # 前10秒钩子/立论
        elif start >= 0.85 * video_dur:
            pos = 0.7                       # 结尾总结段
        elif gap_before > 3.0:
            pos = 0.6                       # 长停顿后 = 新段落起始
        else:
            pos = 0.2                       # 正文普通句

        # 2) 时长/停顿伪声学
        speech_rate = len(text) / dur if dur > 0 else 0.0
        rate_factor = 1.0 if (avg_speech_rate > 0 and speech_rate > 1.2 * avg_speech_rate) else 0.4
        pause_factor = min(1.0, gap_before / 5.0)
        dur_score = 0.5 * pause_factor + 0.5 * rate_factor

        # 3) 重复度（字符频率中心度）
        freqs = [char_counter.get(ch, 0) / max_c for ch in _norm_cn(text)
                 if ch in char_counter and ch not in _STOP_CHARS]
        rep_score = (sum(freqs) / len(freqs)) if freqs else 0.0

        # 4) 修辞话术（FT4 规则兜底，确定性；只扫本句自身，不扫全文避免误归因）
        red_flags, weasel, hedge_lvl = apply_rhetoric_rules(text, "")
        rhet_raw = 0.4 * min(len(red_flags), 2) + (0.2 if weasel else 0) + (0.1 if hedge_lvl == 0 else 0)
        rhet_score = min(1.0, rhet_raw)

        # 5) 强调标点
        pn = len(_PUNCT_RE.findall(text))
        punct_score = min(1.0, pn / 2.0)

        # 6) 情绪弱代理（弹幕密度）
        bucket = int(start // 30)
        emo_score = min(1.0, danmaku_density.get(bucket, 0) / max_danmaku) if danmaku else 0.0

        # 7) 钩子句（前10秒）
        hook_score = 1.0 if start <= 10.0 else 0.0

        salience = (W_POS * pos + W_DUR * dur_score + W_REP * rep_score
                    + W_RHET * rhet_score + W_PUNCT * punct_score
                    + W_EMO * emo_score + W_HOOK * hook_score)

        flags = [f"绝对化话术:{f}" for f in red_flags]
        if weasel:
            flags.append("水词")
        if hedge_lvl == 2:
            flags.append("强模糊语")

        # 重叠窗口保险：取相邻句（gap<2s）作上下文，防跨句主张（"先做A再做B"）漏抽
        ctx = [text]
        if i > 0 and (start - bounds[i - 1]["end"]) < 2.0:
            ctx.insert(0, bounds[i - 1]["text"])
        if i < n - 1 and (bounds[i + 1]["start"] - end) < 2.0:
            ctx.append(bounds[i + 1]["text"])

        results.append({
            "ts": b["ts"],
            "start": start,
            "text": text,
            "salience": round(salience, 4),
            "signals": {
                "pos": round(pos, 3), "dur": round(dur_score, 3),
                "rep": round(rep_score, 3), "rhet": round(rhet_score, 3),
                "punct": round(punct_score, 3), "emo": round(emo_score, 3),
                "hook": round(hook_score, 3),
            },
            "flags": flags,
            "context": ctx,
        })

    # ── v0.4.6 时间桶覆盖：强制骨架横跨整段视频，治前倾偏差 ──
    # 旧行为：纯显著度 Top-K 让片头(钩子+位置双加成)与片尾垄断 Top-12，
    # 中后段(占全片~75%时长)仅 1 句 → CE1+CE2 抽主张结构性漏抽中部关键主张（静默偏盲，不崩溃）。
    # 新行为：视频均分 top_k 个时间桶，每桶取显著度最高的句子 → 骨架必横跨整段；
    # 空桶(静默段)从全局剩余显著度 Top 补足，保证返回 top_k 条且尽量时间均匀。
    nb = max(1, top_k)
    buckets = [[] for _ in range(nb)]
    for r in results:
        st = r.get("start", 0.0)
        bi = min(nb - 1, int(st / video_dur * nb)) if video_dur > 0 else 0
        buckets[bi].append(r)
    chosen = []
    for bi, b in enumerate(buckets):
        if not b:
            continue
        best = max(b, key=lambda r: r["salience"])
        best = dict(best)
        best["bucket"] = bi
        best["bucket_range"] = [round(bi * video_dur / nb, 1), round((bi + 1) * video_dur / nb, 1)]
        chosen.append(best)
    # 空桶补足：从全局剩余显著度 Top 补，保证返回 top_k 条
    if len(chosen) < top_k:
        used_ids = {id(c) for c in chosen}
        remainder = sorted((r for r in results if id(r) not in used_ids),
                           key=lambda r: r["salience"], reverse=True)
        for r in remainder:
            if len(chosen) >= top_k:
                break
            rc = dict(r)
            rc["bucket"] = -1  # 补足桶（非时间均匀，仅静默段不足时）
            chosen.append(rc)
    # 按时间排序（便于阅读与下游消费），重排 rank
    chosen.sort(key=lambda r: r.get("start", 0.0))
    for rank, r in enumerate(chosen[:top_k], 1):
        r["rank"] = rank
    return chosen[:top_k]
