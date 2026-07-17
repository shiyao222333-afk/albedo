"""通用锚定闸门（AC4 / AC5 · v0.4.8）

确定性（非 LLM）保真自检：逐条核对"抽取项"（SOP 步骤 / 大纲 / 主张 / 摘要要点）
是否能在**真实字幕**里找到依据，根治鲁棒性测试暴露的"编造 SOP 步骤带假时间戳"
致命问题（run2/run3 各编出一份字幕里不存在的 SOP）。

与 core/grounding.py（LLM 版 summary 忠实性检查，标 ⚠️ 不删）的区别：
  - grounding.py：摘要要点 → LLM 判 supported → 未支撑标 ⚠️ 保留（防误杀）
  - ground_extract.py：SOP 步骤等 → 程序化子串+时间戳核对 → 编造项**直接剔除**
    （用户拍板：SOP 步骤编造必须剔除，不能留着误导"可照搬"）

判定逻辑（每条 item 需含 'ts' 与 'text'）：
  text_ok  : 归一化 item 文本中存在一段足够长的连续子串命中字幕 blob
             → 文本确实出自字幕，铁定可信，直接判 grounded
  ts_points: 从 ts 抽出的所有 'mm:ss' 点（含 'a~b' 范围两端）
  ts_all_ok: ts_points 全部能在真实字幕时间戳窗口内命中（范围两端都要真）
             → None 表示 item 无 ts 信息 / False 表示有假时间戳 / True 表示全真

  决策：
    text_ok                              → grounded（保留）
    not text_ok & ts_all_ok is False     → ungrounded: fabricated（时间戳也是假的 = 编造）
    not text_ok & ts_all_ok is True      → ungrounded: soft_paraphrase（ts 真但文本不在字幕）
    not text_ok & ts_all_ok is None      → ungrounded: no_support（无 ts 且文本不在字幕）

  调用方按 kind 执行策略：
    sop   → 剔除全部 ungrounded（用户：编造步骤直接剔除）
    claim/outline/generic → 保留 ungrounded 并打 ⚠️（后续由各自报告逻辑标出）

纯函数、零 LLM、不抛；无字幕 → 全部判定为 grounded（无法核查，降级不误杀）。
"""
from __future__ import annotations

import re
from typing import Optional

# 归一化：去掉空白与标点，保留 CJK + 字母数字，便于子串比对
_PUNCT = re.compile(r"[\s\W_]+", flags=re.UNICODE)
_TS_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _norm(t: str) -> str:
    if not t:
        return ""
    # 去所有非"字"字符（含空格/标点/emoji），CJK 字母数字保留
    return _PUNCT.sub("", t)


def _parse_ts_points(ts: str) -> list:
    """从 ts 抽所有 'mm:ss' 点（含 'a~b' 范围两端）→ 秒数列表。无则空。"""
    pts = []
    for m in _TS_RE.finditer(ts or ""):
        pts.append(int(m.group(1)) * 60 + int(m.group(2)))
    return pts


def _build_sub_index(subtitle_lines: list):
    """返回 (blob_norm, sub_secs:list)。sub_secs 来自 ts 字符串，缺则回退 start。"""
    blob_parts = []
    secs = []
    for s in (subtitle_lines or []):
        if not isinstance(s, dict):
            continue
        text = s.get("text", "")
        if text:
            blob_parts.append(_norm(text))
        # 时间戳：优先 ts 字符串，回退 start 浮点
        sec = None
        ts = s.get("ts")
        if ts:
            ps = _parse_ts_points(ts)
            if ps:
                sec = ps[0]
        if sec is None:
            st = s.get("start")
            if isinstance(st, (int, float)):
                sec = float(st)
        if sec is not None:
            secs.append(sec)
    return "".join(blob_parts), secs


def _text_ok(tn: str, blob: str, k: int) -> bool:
    """tn 中是否存在长度 >= k 的连续子串出现在 blob。tn 过短 → 从宽保留。"""
    if not tn:
        return False
    if len(tn) < 4:
        return True  # 太短无法判定，默认可信，避免误杀短步骤
    k = min(k, len(tn))
    if k <= 0:
        return True
    for i in range(len(tn) - k + 1):
        if tn[i:i + k] in blob:
            return True
    return False


def _ts_all_ok(ts_points: list, sub_secs: list, window_sec: float) -> Optional[bool]:
    """ts_points 全部命中真实字幕时间戳窗口 → True；任一不命中 → False；无点 → None。"""
    if not ts_points:
        return None
    if not sub_secs:
        return False  # 有 ts 但无任何真实字幕时间戳可比对 → 视为不可核（保守 False）
    for p in ts_points:
        hit = False
        for s in sub_secs:
            if abs(p - s) <= window_sec:
                hit = True
                break
        if not hit:
            return False
    return True


def gate_extract(
    items: list,
    subtitle_lines: list,
    *,
    kind: str = "generic",
    window_sec: float = 30.0,
) -> dict:
    """确定性锚定闸门。

    参数：
      items:          list[{ts, text, ...}]（也兼容仅 text 无 ts）
      subtitle_lines: 真实字幕 [{ts, text, start, ...}]
      kind:           'sop' | 'claim' | 'outline' | 'generic'（仅影响 reason 文案，
                      策略由调用方据 kind 决定保留/剔除）
      window_sec:     ts 命中真实字幕的时间窗口（秒），默认 30s 容错

    返回：
      {
        "grounded":   [item, ...],                         # 通过锚定
        "ungrounded": [{"item":item, "code":str, "reason":str}, ...],
        "checked": int, "n_grounded": int, "n_ungrounded": int,
        "kind": str,
      }
    """
    blob, sub_secs = _build_sub_index(subtitle_lines)
    # 无字幕 → 无法核查，全部判定为 grounded（降级不误杀，绝不空手剔除）
    if not subtitle_lines:
        items = list(items or [])
        return {
            "grounded": items,
            "ungrounded": [],
            "checked": len(items),
            "n_grounded": len(items),
            "n_ungrounded": 0,
            "kind": kind,
        }
    grounded = []
    ungrounded = []
    for it in (items or []):
        if not isinstance(it, dict):
            # 非字典项无法核查，默认保留（不丢信息）
            grounded.append(it)
            continue
        text = it.get("text", "")
        tn = _norm(text)
        # 阈值：越长容忍越多改写，但至少 6 字连续命中；上限 10
        k = min(10, max(6, len(tn) // 2)) if tn else 6
        text_ok = _text_ok(tn, blob, k)

        if text_ok:
            grounded.append(it)
            continue

        # 文本不在字幕 → 进一步看 ts
        ts_points = _parse_ts_points(it.get("ts", ""))
        tall = _ts_all_ok(ts_points, sub_secs, window_sec)
        if tall is False:
            code, reason = "fabricated", "文本不在字幕且时间戳无依据（疑似编造）"
        elif tall is True:
            code, reason = "soft_paraphrase", "文本不在字幕（疑似改写），但时间戳真实"
        else:
            code, reason = "no_support", "文本不在字幕且无时间戳可核对"
        ungrounded.append({"item": it, "code": code, "reason": reason})

    return {
        "grounded": grounded,
        "ungrounded": ungrounded,
        "checked": len(items or []),
        "n_grounded": len(grounded),
        "n_ungrounded": len(ungrounded),
        "kind": kind,
    }


def apply_sop_gate(
    sop_dict: dict,
    subtitle_lines: list,
    *,
    window_sec: float = 30.0,
) -> dict:
    """对 SOP 四张表应用闸门：剔除全部 ungrounded 项（用户：编造步骤直接剔除）。

    参数 sop_dict: {'purpose','preconditions':[{text,ts}],'steps':[...],
                    'warnings':[...],'completion_checklist':[...]}
    返回：过滤后的 sop_dict + '_gate' 元数据（被剔除数与原因汇总，供报告展示）。
    """
    if not isinstance(sop_dict, dict):
        return sop_dict or {}
    out = dict(sop_dict)
    dropped_total = 0
    reasons = []
    for key in ("preconditions", "steps", "warnings", "completion_checklist"):
        items = sop_dict.get(key) or []
        if not items:
            continue
        res = gate_extract(items, subtitle_lines, kind="sop", window_sec=window_sec)
        out[key] = res["grounded"]
        if res["n_ungrounded"]:
            dropped_total += res["n_ungrounded"]
            for u in res["ungrounded"]:
                reasons.append(f"{key}: {u['code']} — {_str(u['item'].get('text',''))[:40]}")
    out["_gate"] = {
        "checked": (sop_dict.get("_gate", {}) or {}).get("checked", 0)
        + sum(len(sop_dict.get(k) or []) for k in
              ("preconditions", "steps", "warnings", "completion_checklist")),
        "dropped": dropped_total,
        "reasons": reasons,
    }
    return out


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def apply_flag_gate(
    items: list,
    subtitle_lines: list,
    *,
    kind: str = "generic",
    window_sec: float = 30.0,
):
    """保留策略（claim / outline 等）：保留全部项，但给 ungrounded 项打 '_ungrounded' 标记。

    返回 (out_items, meta)。out_items 顺序与原 items 一致，ungrounded 项被复制并加
    '_ungrounded'=<reason>，供报告标 ⚠️（不删除，留待用户核对）。
    """
    items = list(items or [])
    if not items:
        return items, {"checked": 0, "flagged": 0, "reasons": []}
    res = gate_extract(items, subtitle_lines, kind=kind, window_sec=window_sec)
    # ungrounded item 对象 → reason 映射（按 id 定位，保持顺序）
    reason_by_id = {id(u["item"]): u for u in res["ungrounded"]}
    out = []
    reasons = []
    for it in items:
        rid = reason_by_id.get(id(it))
        if rid is not None:
            marked = dict(it)
            marked["_ungrounded"] = rid["reason"]
            out.append(marked)
            reasons.append(f"{kind}: {rid['code']} — {_str(it.get('text', ''))[:40]}")
        else:
            out.append(it)
    return out, {"checked": res["checked"], "flagged": len(res["ungrounded"]), "reasons": reasons}
