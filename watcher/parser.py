"""中转①解析：{bv}.md（YAML frontmatter + 结构化正文） → AlbedoInput

依赖自由（不引 pyyaml）：frontmatter 是简单标量 key:value，值由 json.dumps 包裹，做轻量解析即可。

正文按 '# 标题' 分节解析（2026-07-15 内容线增强）：
  # 字幕            → subtitle_lines: [{ts:"mm:ss", start:float, text}]
  # 高光时间点       → highlights:     [{ts:"mm:ss", start:float, content}]
  # 弹幕（去重过滤后）→ danmaku:       [{time:float, text}]
  # 置顶评论         → comments_pinned:[{user, likes, pin_type, text}]
  # 高赞评论         → comments_top:   [{user, likes, text}]
  # AI 摘要          → ai_conclusion:  str

向后兼容：旧版中转文件（字幕无 [mm:ss] 时间戳）逐行降级，start=-1、ts=""，
           内容不丢，仅无法做"按条数锚定"。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.models import AlbedoInput


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

# 字幕: [mm:ss] 文本
_TS_LINE = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*(.+?)\s*$")
# 高光: - [mm:ss] 内容（行首带 '- '）
_HL_LINE = re.compile(r"^-\s*\[(\d{1,2}):(\d{2})\]\s*(.+?)\s*$")
# 弹幕: [123s] 文本
_DM_LINE = re.compile(r"^\[(\d+)(?:\.\d+)?s\]\s*(.+?)\s*$")
# 置顶: [X赞 · 标签] 用户: 文本
_PIN_LINE = re.compile(r"^\[(.+?)赞\s*·\s*(.+?)\]\s*(.+?):\s*(.+?)\s*$")
# 高赞: [X赞] 用户: 文本
_TOP_LINE = re.compile(r"^\[(.+?)赞\]\s*(.+?):\s*(.+?)\s*$")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        try:
            return json.loads(v)
        except Exception:
            return v[1:-1]
    return v


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_int(v):
    """互动计数可能是 float(如 2426.0)，展示时去小数点。"""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _parse_engagement(fields: dict) -> dict:
    """AI 设计决策（非用户指令，待确认）：从 Nigredo 中转 frontmatter 解析互动数据
    进 signals["engagement"]。仅保留非 null 字段，缺失即不写，保证旧 transit 文件
    缺字段时向后兼容、不崩。计数/比率原样搬运（Nigredo 已算好百分比），不重算避免漂移。
    """
    out = {}
    for key in (
        "view_count", "like_count", "coin_count", "favorite_count",
        "share_count", "comment_count", "danmaku_count",
        "like_rate", "favorite_rate", "coin_rate",
    ):
        v = _num(fields.get(key))
        if v is not None:
            out[key] = v
    d_total = _num(fields.get("danmaku_total_before"))
    if d_total is not None:
        out["danmaku_total_before"] = d_total
    return out


def _parse_keywords(raw: str) -> list:
    """transit① frontmatter 的 keywords 是 JSON 列表字符串（如 '["a", "b"]'），
    解析为 str 列表；解析失败返回空列表（refine 输出侧对空有熔知 LLM 兜底）。
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass
    return []


def _split_sections(body: str) -> dict[str, list[str]]:
    """按 '# 标题' 把正文切成 {标题: 行列表}（不含标题行本身）。"""
    sections: dict[str, list[str]] = {}
    cur: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            if cur is not None:
                sections[cur] = buf
            cur = m.group(1)
            buf = []
        else:
            if cur is not None:
                buf.append(line)
    if cur is not None:
        sections[cur] = buf
    return sections


def _section_lines(sections: dict[str, list[str]], *names: str) -> list[str]:
    for n in names:
        if n in sections:
            return sections[n]
    return []


def parse_transit_md(path: str | Path) -> AlbedoInput:
    """读 {bv}.md，解析 frontmatter 字段 + 分节正文，组装 AlbedoInput。"""
    text = Path(path).read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # 无 frontmatter：整文件当纯文本（极旧文件降级）
        return AlbedoInput(text=text.strip(), text_type="subtitle")
    meta_block, body = m.group(1), m.group(2)
    fields: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fields[key.strip()] = _unquote(val)

    sections = _split_sections(body)
    if not sections:
        # 有 frontmatter 但无分节：整 body 当纯文本降级
        return AlbedoInput(
            text=body.strip(),
            text_type="subtitle",
            video_id=fields.get("video_id", ""),
            title=fields.get("title", ""),
            up_name=fields.get("up_name", ""),
            source_url=fields.get("source_url", ""),
            keywords=_parse_keywords(fields.get("keywords", "")),
            signals={
                "platform": fields.get("platform", "bilibili"),
                "engagement": _parse_engagement(fields),
            },
            published=fields.get("pubdate", "") or "",
        )

    # —— 字幕 ——
    subtitle_lines: list[dict] = []
    for ln in _section_lines(sections, "字幕"):
        ln = ln.strip()
        if not ln:
            continue
        tm = _TS_LINE.match(ln)
        if tm:
            mm, ss = int(tm.group(1)), int(tm.group(2))
            subtitle_lines.append({
                "ts": f"{mm:02d}:{ss:02d}",
                "start": mm * 60 + ss,
                "text": tm.group(3),
            })
        else:
            # 旧格式无时间戳：整行作一条，start=-1 标记不可锚定
            subtitle_lines.append({"ts": "", "start": -1.0, "text": ln})

    # —— 高光时间点 ——
    highlights: list[dict] = []
    for ln in _section_lines(sections, "高光时间点"):
        ln = ln.strip()
        tm = _HL_LINE.match(ln)
        if tm:
            mm, ss = int(tm.group(1)), int(tm.group(2))
            highlights.append({
                "ts": f"{mm:02d}:{ss:02d}",
                "start": mm * 60 + ss,
                "content": tm.group(3),
            })

    # —— 弹幕 ——
    danmaku: list[dict] = []
    for ln in _section_lines(sections, "弹幕（去重过滤后）", "弹幕"):
        ln = ln.strip()
        tm = _DM_LINE.match(ln)
        if tm:
            danmaku.append({"time": _num(tm.group(1)) or 0.0, "text": tm.group(2)})

    # —— 置顶评论 ——
    comments_pinned: list[dict] = []
    for ln in _section_lines(sections, "置顶评论"):
        ln = ln.strip()
        tm = _PIN_LINE.match(ln)
        if tm:
            comments_pinned.append({
                "likes": tm.group(1).strip(),
                "pin_type": tm.group(2).strip(),
                "user": tm.group(3).strip(),
                "text": tm.group(4).strip(),
            })

    # —— 高赞评论 ——
    comments_top: list[dict] = []
    for ln in _section_lines(sections, "高赞评论"):
        ln = ln.strip()
        tm = _TOP_LINE.match(ln)
        if tm:
            comments_top.append({
                "likes": tm.group(1).strip(),
                "user": tm.group(2).strip(),
                "text": tm.group(3).strip(),
            })

    # —— AI 摘要 ——
    ai_conclusion = "\n".join(
        ln.strip() for ln in _section_lines(sections, "AI 摘要") if ln.strip()
    )

    # —— 播放分析（frontmatter 标量，仅内容线备用，形式线才深度用）——
    play_analysis: dict = {}
    if fields.get("play_analysis_available") in ("true", "True"):
        pa = {
            "three_sec_retention": _num(fields.get("three_sec_retention")),
            "avg_play_duration": _num(fields.get("avg_play_duration")),
            "completion_rate": _num(fields.get("completion_rate")),
        }
        if any(v is not None for v in pa.values()):
            play_analysis = pa

    return AlbedoInput(
        text=body.strip(),
        text_type="subtitle",
        video_id=fields.get("video_id", ""),
        title=fields.get("title", ""),
        up_name=fields.get("up_name", ""),
        source_url=fields.get("source_url", ""),
        keywords=_parse_keywords(fields.get("keywords", "")),
        signals={
            "platform": fields.get("platform", "bilibili"),
            "engagement": _parse_engagement(fields),
        },
        published=fields.get("pubdate", "") or "",
        subtitle_lines=subtitle_lines,
        highlights=highlights,
        danmaku=danmaku,
        comments_pinned=comments_pinned,
        comments_top=comments_top,
        ai_conclusion=ai_conclusion,
        play_analysis=play_analysis,
    )
