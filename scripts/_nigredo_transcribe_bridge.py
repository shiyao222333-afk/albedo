"""馏析→炼真 桥接（真实管线）：用 Nigredo 的下载 + Whisper ASR 产出 Albedo 兼容字幕。

仅依赖 Nigredo 栈（system Python 3.14: yt_dlp / faster_whisper / bilibili_api）。
输出 data/out/subtitle_lines_<BVID>.json，供 run_robustness_test.py 消费。

用法（必须用 system Python 3.14 跑，因 yt_dlp/faster_whisper 装在那里）：
    C:\Python314\python.exe scripts/_nigredo_transcribe_bridge.py <BVID>
"""
import os
import re
import sys
import json
import shutil
import urllib.request
from pathlib import Path

# 只注入 Nigredo（避免 Albedo 的 core 抢占同名包）
sys.path.insert(0, r"D:\nigredo")

from platforms.bilibili import BilibiliPlatform
from core.subtitle import transcribe_with_whisper

TMP = Path(r"D:\albedo\data\_ingest_tmp")
OUT = Path(r"D:\albedo\data\out")
NIGREDO_ENV = Path(r"D:\nigredo\.env")


def _read_cookie() -> str:
    if NIGREDO_ENV.exists():
        t = NIGREDO_ENV.read_text(encoding="utf-8")
        m = re.search(r"^BILIBILI_COOKIE\s*=\s*(.*)$", t, re.M)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return os.environ.get("BILIBILI_COOKIE", "")


def _fetch_title(bvid: str) -> str:
    try:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
        return d.get("data", {}).get("title", "")
    except Exception as e:
        print("[title] 获取失败（不影响转写）:", repr(e)[:120])
        return ""


def _sec_to_ts(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def main():
    bvid = sys.argv[1] if len(sys.argv) > 1 else "BV1pQ7o61EMh"
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    title = _fetch_title(bvid)
    print(f"[馏析] 目标：{bvid} | {title}")

    # .env 的 BILIBILI_COOKIE 仅 43 字符（占位/失效），会导致 412。
    # 跳过它，改走浏览器已登录 Cookie 兜底（--cookies-from-browser）。
    cookie = _read_cookie()
    if not cookie or "SESSDATA=" not in cookie or len(cookie) < 60:
        cookie = ""
        print("[馏析] .env 无有效 Cookie，改走浏览器已登录 Cookie 兜底")
    else:
        print("[馏析] 使用 .env Cookie")

    browsers = ["firefox", "chrome", "edge", "brave"]
    audio = None
    last_err = None
    for br in browsers:
        try:
            plat = BilibiliPlatform(cookie=cookie, browser=br)
            print(f"[馏析] 下载音频 (yt-dlp, browser={br}) ...")
            audio = plat.download_audio(bvid, str(TMP))
            break
        except RuntimeError as e:
            last_err = e
            msg = str(e)
            if "412" in msg or "Precondition" in msg:
                print(f"[馏析] {br} Cookie 不可用（412），换浏览器重试")
                continue
            raise
    if audio is None:
        raise RuntimeError(f"所有浏览器 Cookie 均不可用：{last_err}") from last_err
    print(f"[馏析] 音频已下载：{audio}")

    print("[馏析] Whisper ASR (large-v3, cuda) ...")
    segs = transcribe_with_whisper(audio)
    print(f"[馏析] 转写完成：{len(segs)} 段")

    lines = [{
        "ts": _sec_to_ts(s["start"]),
        "start": s["start"],
        "end": s["end"],
        "text": s["text"],
    } for s in segs]

    out = {
        "video_id": bvid,
        "title": title,
        "source": "whisper",
        "subtitle_lines": lines,
    }
    out_path = OUT / f"subtitle_lines_{bvid}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    full_text_len = sum(len(s["text"]) for s in lines)
    print(f"[馏析→炼真] 已写出 {len(lines)} 条字幕（总字数≈{full_text_len}）→ {out_path}")

    # 清理临时音频，省空间
    try:
        if os.path.exists(audio):
            os.remove(audio)
            print(f"[cleanup] 已删临时音频 {audio}")
    except Exception as e:
        print("[cleanup] 删音频失败（忽略）:", repr(e)[:80])


if __name__ == "__main__":
    main()
