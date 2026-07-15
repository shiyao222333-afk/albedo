"""内容线核心处理（#76 #77 #78）

三条管线，全部针对字幕类输入（AlbedoInput.subtitle_lines 非空）：

1. extract_key_sentences（#76 Route A：先抄关键原话再改写）
   - 先从字幕挑"信息密度高"的关键原话（逐字、带 ts）→ key_sentences（兜底，原文不丢）
   - 基于 key_sentences 生成摘要（gist + bullets），每条 bullet 标 source_ts 指回字幕
   - 措辞可变、内容一致：因为改写只基于挑出的原话，模型无法凭空编

2. build_highlight_blocks（#77 高光上下文块）
   - 对每条高光时间点，取前后各 ±N 条字幕（按时间轴锚定），捆绑邻近弹幕/评论
   - 组成"高光上下文块"，供按类型萃取时优先深挖（观众最兴奋处）

3. extract_by_type（#78 按类型萃取）
   - 按 classify 结果分流：tutorial→SOP / tool_review→决策表 / opinion→论点图 /
     knowledge→概念卡 / entertainment→标记转形式线 / narrative→带ts大纲
   - 每个要点带 ts 锚定字幕，保证可溯源、不丢关键信息

确定性：全部走 call_llm_json（temperature=0 + 固定 schema 枚举）。
鲁棒：每步 try/except 降级，失败不阻断主流程。
"""
from __future__ import annotations

from core.llm import call_llm_json


# ───────────────────────────────────────── #76 Route A ─────────────────────────────────────────

_KEY_SENTENCE_SYSTEM = """你是视频内容精炼助手。任务分两步：
第一步：从字幕中挑出"信息密度高"的关键原话句——逐字原样摘出（不要改写、不要合并），保留其时间戳 [mm:ss]。
        只挑真正承载核心观点/步骤/结论/数据的句子，通常 8-20 句。
第二步：基于挑出的关键原话，生成摘要：
        - gist: 一句话说清这条视频的核心内容
        - bullets: 5-12 条要点，每条是可理解、可照搬的精炼表述；每条必须标 source_ts，
          指向它依据的那条关键原话/字幕的时间戳（必须是字幕中真实存在的 [mm:ss]）。

只输出 JSON（不要任何解释）：
{
  "key_sentences": [{"ts":"mm:ss","text":"<原话>"}, ...],
  "summary": {"gist":"<一句话核心>","bullets":[{"text":"<要点>","source_ts":"mm:ss"}, ...]}
}"""


def extract_key_sentences(
    subtitle_lines: list,
    title: str = "",
    ai_conclusion: str = "",
    llm_kwargs: dict = None,
) -> dict:
    """Route A：关键原话兜底 + 改写摘要。返回 {key_sentences, summary}。"""
    subs = "\n".join(
        f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subtitle_lines
    )
    user = f"标题：{title}\n\nAI摘要：{ai_conclusion}\n\n字幕全文：\n{subs}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _KEY_SENTENCE_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=3000,
            **(llm_kwargs or {}),
        )
        key_sentences = data.get("key_sentences") or []
        summary = data.get("summary") or {}
        # 规整：确保字段存在
        if not isinstance(summary, dict):
            summary = {}
        summary.setdefault("gist", "")
        summary.setdefault("bullets", [])
        return {"key_sentences": key_sentences, "summary": summary}
    except Exception:
        # 降级：无关键句，摘要退化为 AI 摘要/标题
        return {
            "key_sentences": [],
            "summary": {"gist": ai_conclusion or title,
                        "bullets": []},
        }


# ───────────────────────────────────────── #77 高光上下文块 ─────────────────────────────────────────

def build_highlight_blocks(
    highlights: list,
    subtitle_lines: list,
    danmaku: list = None,
    comments_top: list = None,
    comments_pinned: list = None,
    window: int = 15,
) -> list:
    """对每条高光，取前后各 ±window 条字幕（按时间轴锚定），捆绑邻近弹幕/评论。

    纯函数（无 LLM）。start=-1（旧格式无时间戳）的字幕无法锚定，会并入离其最近的块兜底。
    返回 list[{ts, content, subtitle_window:[{ts,text}], danmaku:[...], comments:[...]}]。
    """
    danmaku = danmaku or []
    comments_top = comments_top or []
    comments_pinned = comments_pinned or []

    # 字幕按 start 升序；start<0 的放末尾（无法锚定，作为兜底池）
    anchored = sorted(
        [s for s in subtitle_lines if isinstance(s.get("start"), (int, float)) and s["start"] >= 0],
        key=lambda s: s["start"],
    )
    unanchored = [s for s in subtitle_lines if not (isinstance(s.get("start"), (int, float)) and s["start"] >= 0)]

    def _nearest_idx(t: float) -> int:
        if not anchored:
            return -1
        lo, hi = 0, len(anchored) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if anchored[mid]["start"] < t:
                lo = mid + 1
            else:
                hi = mid
        return lo

    blocks = []
    for hl in highlights:
        t = hl.get("start", 0) or 0
        idx = _nearest_idx(t)
        if idx == -1:
            window_subs = list(anchored[:window * 2 + 1]) + unanchored
        else:
            lo = max(0, idx - window)
            hi = min(len(anchored), idx + window + 1)
            window_subs = list(anchored[lo:hi]) + unanchored
        # 邻近弹幕：time 在高光 ±30s 内
        near_dm = [
            d for d in danmaku
            if isinstance(d.get("time"), (int, float)) and abs(d["time"] - t) <= 30
        ]
        blocks.append({
            "ts": hl.get("ts", ""),
            "content": hl.get("content", ""),
            "subtitle_window": window_subs,
            "danmaku": near_dm,
            "comments": list(comments_top) + list(comments_pinned),
        })
    return blocks


# ───────────────────────────────────────── #78 按类型萃取 ─────────────────────────────────────────

def extract_by_type(
    content_type: str,
    key_sentences: list,
    summary: dict,
    highlight_blocks: list,
    title: str = "",
    ai_conclusion: str = "",
    llm_kwargs: dict = None,
) -> dict:
    """按内容类型分流萃取，返回对应结构 dict（每个要点带 ts 锚定）。"""
    ks_text = "\n".join(f"[{k.get('ts','')}] {k.get('text','')}" for k in key_sentences)
    hl_text = "\n\n".join(
        f"【高光 {b.get('ts','')}】{b.get('content','')}\n"
        + "\n".join(f"  [{s.get('ts','')}] {s.get('text','')}" for s in b.get("subtitle_window", []))
        + ("\n  弹幕：" + " / ".join(d.get("text","") for d in b.get("danmaku", [])[:10]) if b.get("danmaku") else "")
        for b in highlight_blocks
    )
    context = f"标题：{title}\n\nAI摘要：{ai_conclusion}\n\n关键原话：\n{ks_text}\n\n高光上下文：\n{hl_text}"

    if content_type == "tutorial":
        return _extract_sop(context, llm_kwargs)
    if content_type == "tool_review":
        return _extract_decision(context, llm_kwargs)
    if content_type == "opinion":
        return _extract_claim(context, llm_kwargs)
    if content_type == "knowledge":
        return _extract_concept(context, llm_kwargs)
    if content_type == "entertainment":
        return {"route_to_form": True,
                "note": "纯娱乐内容，内容线无信息可萃取；其价值在形式/表达线（研究它怎么勾人、人设、节奏）。"}
    if content_type == "narrative":
        return _extract_outline(context, llm_kwargs)
    # unknown → 通用
    return _extract_generic(context, summary, llm_kwargs)


def _extract_sop(context: str, llm_kwargs: dict) -> dict:
    """教程 → 完整 SOP（用户决策 B：连细节：准备/步骤/验证/收尾）。"""
    sys_p = """从视频中抽取可照搬的标准操作流程(SOP)。每条必须带 ts 锚定字幕。
输出 JSON：
{
  "purpose": "<这条SOP能达成什么>",
  "preconditions": [{"text":"<准备/前置条件>","ts":"mm:ss"}, ...],
  "steps": [{"text":"<步骤>","ts":"mm:ss"}, ...],
  "warnings": [{"text":"<避坑/注意点>","ts":"mm:ss"}, ...],
  "completion_checklist": [{"text":"<怎么确认做对了>","ts":"mm:ss"}, ...]
}"""
    try:
        return {"kind": "sop", **call_llm_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": context}],
            max_tokens=3000, **(llm_kwargs or {}))}
    except Exception:
        return {"kind": "sop", "purpose": "", "preconditions": [], "steps": [],
                "warnings": [], "completion_checklist": []}


def _extract_decision(context: str, llm_kwargs: dict) -> dict:
    """工具测评 → 决策表。"""
    sys_p = """从视频中抽取对"是否使用该工具"的决策信息。每条带 ts。
输出 JSON：
{
  "pros": [{"text":"<优点>","ts":"mm:ss"}, ...],
  "cons": [{"text":"<缺点>","ts":"mm:ss"}, ...],
  "conclusion": "<作者结论>",
  "best_for": "<适合什么人/场景>"
}"""
    try:
        return {"kind": "decision", **call_llm_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": context}],
            max_tokens=2500, **(llm_kwargs or {}))}
    except Exception:
        return {"kind": "decision", "pros": [], "cons": [], "conclusion": "", "best_for": ""}


def _extract_claim(context: str, llm_kwargs: dict) -> dict:
    """观点评论 → 论点图。"""
    sys_p = """从视频中抽取作者的核心论点与论据。每条带 ts。
输出 JSON：
{
  "claim": "<核心主张>",
  "evidence": [{"text":"<论据>","ts":"mm:ss"}, ...],
  "stance": "<作者立场/倾向>",
  "counter": [{"text":"<作者反驳的相反观点>","ts":"mm:ss"}, ...]
}"""
    try:
        return {"kind": "claim", **call_llm_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": context}],
            max_tokens=2500, **(llm_kwargs or {}))}
    except Exception:
        return {"kind": "claim", "claim": "", "evidence": [], "stance": "", "counter": []}


def _extract_concept(context: str, llm_kwargs: dict) -> dict:
    """知识科普 → 概念卡。"""
    sys_p = """从视频中抽取核心概念讲解。每条带 ts。
输出 JSON：
{
  "concept": "<概念名>",
  "definition": "<定义/是什么>",
  "example": [{"text":"<例子/类比>","ts":"mm:ss"}, ...]
}"""
    try:
        return {"kind": "concept", **call_llm_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": context}],
            max_tokens=2000, **(llm_kwargs or {}))}
    except Exception:
        return {"kind": "concept", "concept": "", "definition": "", "example": []}


def _extract_outline(context: str, llm_kwargs: dict) -> dict:
    """叙事故事 → 带 ts 大纲。"""
    sys_p = """从视频中抽取内容大纲（按时间顺序）。每条带 ts。
输出 JSON：
{
  "overview": "<整体讲什么>",
  "sections": [{"ts":"mm:ss","subtitle":"<段落主题>","points":["<要点>", ...]}, ...]
}"""
    try:
        return {"kind": "outline", **call_llm_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": context}],
            max_tokens=2500, **(llm_kwargs or {}))}
    except Exception:
        return {"kind": "outline", "overview": "", "sections": []}


def _extract_generic(context: str, summary: dict, llm_kwargs: dict) -> dict:
    """未知类型 → 通用要点（复用摘要，保证不丢关键信息）。"""
    bullets = summary.get("bullets", []) if isinstance(summary, dict) else []
    return {
        "kind": "generic",
        "gist": summary.get("gist", "") if isinstance(summary, dict) else "",
        "key_points": bullets,
    }
