"""SRT / 纯文本字幕 → Albedo subtitle_lines.json 转换器（Nigredo 爬取落盘复用）。

用法：
  python scripts/srt_to_subtitle_lines.py <video_id> <input.srt> [--title "标题"]
  python scripts/srt_to_subtitle_lines.py <video_id> <input.txt> --plain   # 纯文本无时间戳

输出：data/<video_id>_subs.json（Nigredo 兼容：{video_id,title,source,subtitle_lines:[{ts,start,end,text}]}）
供 scripts/run_robustness_test.py 直接消费。
"""
from __future__ import annotations

import json
import os
import re
import sys

SRT_BLOCK = re.compile(
    r"(\d+)\s*\n(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*\n(.*?)(?=\n\d+\s*\n|\Z)",
    re.DOTALL,
)


def _to_sec(ts: str) -> float:
    ts = ts.replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _ts(mmss: float) -> str:
    m = int(mmss // 60)
    s = int(mmss % 60)
    return f"{m:02d}:{s:02d}"


def parse_srt(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    out = []
    for idx, start, end, text in SRT_BLOCK.findall(raw):
        text = " ".join(text.strip().splitlines())
        if not text:
            continue
        st, en = _to_sec(start), _to_sec(end)
        out.append({"ts": _ts(st), "start": st, "end": en, "text": text})
    return out


def parse_plain(path: str):
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    return [{"ts": _ts(i * 5.0), "start": i * 5.0, "end": (i + 1) * 5.0, "text": l}
            for i, l in enumerate(lines)]


def main():
    if len(sys.argv) < 3:
        print("用法：python scripts/srt_to_subtitle_lines.py <video_id> <input.srt|.txt> [--title T] [--plain]")
        sys.exit(1)
    vid, inp = sys.argv[1], sys.argv[2]
    plain = "--plain" in sys.argv
    title = ""
    if "--title" in sys.argv:
        title = sys.argv[sys.argv.index("--title") + 1]
    subs = parse_plain(inp) if plain else parse_srt(inp)
    if not subs:
        print("ERROR: 未解析出任何字幕行", file=sys.stderr)
        sys.exit(2)
    out = {"video_id": vid, "title": title or vid, "source": "bilibili",
           "subtitle_lines": subs}
    os.makedirs("data", exist_ok=True)
    dst = f"data/{vid}_subs.json"
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"OK {vid}: {len(subs)} 条字幕 -> {dst}")


if __name__ == "__main__":
    main()
