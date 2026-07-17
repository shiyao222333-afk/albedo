"""抓取 B站视频字幕为 Nigredo 兼容的 subtitle_lines 格式（用于本地鲁棒性测试，不烧炼真 key）。

免登录：直接用 urllib 调 x/web-interface/view（已验证可达），解析 subtitle.list / ai_subtitle 字幕 URL。
优先 AI 字幕(ASR)，回退 CC。输出 JSON：{video_id, title, source, subtitle_lines:[{ts,start,end,text}]}
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

VIEW_URL = "https://api.bilibili.com/x/web-interface/view?bvid={bvid}"


def _sec_to_ts(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.com",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _body_to_lines(body: list) -> list:
    lines = []
    for seg in body or []:
        content = (seg.get("content") or "").strip()
        if not content:
            continue
        start = float(seg.get("from", 0) or 0)
        end = float(seg.get("to", start + 2) or (start + 2))
        lines.append({"ts": _sec_to_ts(start), "start": start, "end": end, "text": content})
    return lines


def _fetch_subtitle(url: str) -> list:
    data = _http_json(url)
    return _body_to_lines(data.get("body", []))


def main():
    bvid = sys.argv[1] if len(sys.argv) > 1 else "BV1jCNe6zEMb"
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    view = _http_json(VIEW_URL.format(bvid=bvid))
    if view.get("code") != 0:
        print("view API 失败：", view.get("message"))
        sys.exit(2)
    d = view["data"]
    title = d.get("title", "")
    print(f"视频：{title} ({bvid})")

    sub = d.get("subtitle") or {}
    lines = []
    src = ""
    # AI 字幕(ASR) 优先
    ai_list = sub.get("ai_subtitle") or []
    if ai_list:
        url = ai_list[0].get("url") or ai_list[0].get("subtitle_url")
        if url:
            try:
                lines = _fetch_subtitle(url)
                src = "ai_subtitle"
            except Exception as e:
                print("AI 字幕抓取失败：", repr(e)[:160])
    # CC 回退
    if not lines:
        cc_list = sub.get("list") or []
        if cc_list:
            url = cc_list[0].get("subtitle_url") or cc_list[0].get("url")
            if url:
                try:
                    lines = _fetch_subtitle(url)
                    src = "cc_subtitle"
                except Exception as e:
                    print("CC 字幕抓取失败：", repr(e)[:160])

    if not lines:
        print("未取到任何字幕（该视频可能无 CC 也无 AI 字幕，或需登录）。")
        sys.exit(2)

    out = {"video_id": bvid, "title": title, "source": src, "subtitle_lines": lines}
    if not out_path:
        os.makedirs("data/out", exist_ok=True)
        out_path = f"data/out/subtitle_lines_{bvid}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已存 {len(lines)} 条字幕 → {out_path}（来源={src}）")


if __name__ == "__main__":
    main()
