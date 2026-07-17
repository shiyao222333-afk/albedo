"""炼真端到端测试（正确方式）：直接读馏析交接目录的 {bv}.md 产物。

正确架构（不修改馏析、不碰馏析内部缓存）：
  馏析 DownloadManager → 写 {bv}.md 到 WATCH_DIR（= Nigredo OUTPUT_DIR，即交接目录）
  炼真 watcher.parser.parse_transit_md → AlbedoInput   ← 炼真自带解析器
  炼真 flows.refine.refine → 完整鉴定报告

本脚本只做「一次性测试触发」，复用炼真自带解析器 + refine，跑两轮验证
缓存冻结（第2轮命中缓存）是否让结论完全一致，并记录总用时。

用法（cwd=D:\albedo）：
    cd /d/albedo && python scripts/run_real_video.py <BVID>

注意：馏析的摄入由馏析自己的管线完成（其 UI / 入口），产出落到 WATCH_DIR；
本脚本只读那份产物，不反向操作馏析。
"""
import os
import sys
import time
import json
from pathlib import Path

# 把项目根(D:\albedo)注入 sys.path，使 `import config/watcher/flows` 可用
_PROJ_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

from config import WATCH_DIR, OUTPUT_DIR
from watcher.parser import parse_transit_md
from flows.refine import refine

OUT_DIR = Path(r"D:\albedo\data\out")


def main():
    bvid = sys.argv[1] if len(sys.argv) > 1 else "BV1pQ7o61EMh"
    md_path = WATCH_DIR / f"{bvid}.md"
    if not md_path.exists():
        print(f"[FATAL] 交接目录找不到 {bvid}.md —— 请先让馏析产出"
              f"（WATCH_DIR={WATCH_DIR}）")
        sys.exit(2)

    print(f"[READ] 直接读馏析产物: {md_path}")
    inp = parse_transit_md(md_path)
    print(f"[INPUT] title={inp.title!r} up={inp.up_name!r} "
          f"segs={len(inp.subtitle_lines)} video_id={inp.video_id}")

    timings, outs = [], []
    for run_i in range(1, 3):
        t0 = time.time()
        out = refine(inp, cache_enabled=True)
        dt = time.time() - t0
        timings.append(dt)
        outs.append(out)
        label = getattr(out.quality.truthfulness, "label", None) if out.quality else None
        print(f"[RUN{run_i}] elapsed={dt:.1f}s | truth_label={label} "
              f"status={out.status} trust={out.trust_score} "
              f"n_claims={len(out.claim_verifications)}")
        time.sleep(0.3)  # 让缓存落盘

    # 稳定判定（缓存冻结 + form_track 冻结验证）
    labels = [getattr(o.quality.truthfulness, "label", None) if o.quality else None
              for o in outs]
    trusts = [o.trust_score for o in outs]
    # 完整主张指纹：quote + accuracy + confidence（不能只比 quote，否则验真结论变化会被掩盖）
    def _claim_fp(o):
        return "|".join(
            f"{c.get('quote','')}::{c.get('accuracy','')}::{c.get('confidence',0)}"
            for c in o.claim_verifications
        )
    claim_fps = [_claim_fp(o) for o in outs]
    stable_label = len(set(labels)) == 1
    stable_trust = len(set(map(str, trusts))) == 1
    stable_claims = len(set(claim_fps)) == 1

    # 完整报告（取 RUN1）
    final = outs[0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_md = OUT_DIR / f"{bvid}_refined.md"
    out_md.write_text(final.report or "", encoding="utf-8")
    out_meta = OUT_DIR / f"{bvid}_refined.meta.json"
    out_meta.write_text(final.to_json(), encoding="utf-8")

    print("\n=== STABILITY（缓存冻结 + form_track 冻结）===")
    print(f"truth_label 两轮一致: {stable_label} -> {labels}")
    print(f"trust_score 两轮一致: {stable_trust} -> {trusts}")
    print(f"claims 完整一致(含验真结论): {stable_claims}")
    print(f"refine 两轮用时(s):   {['%.1f' % t for t in timings]}")

    # 摄入用时（来自馏析日志，已发生）：INGEST_DONE elapsed=56.3s
    ingest_s = 56.3
    refine_total = sum(timings)
    print(f"\n=== 总用时 ===")
    print(f"馏析摄入(Whisper转写): {ingest_s:.1f}s（已发生，复用）")
    print(f"炼真 refine 两轮:       {refine_total:.1f}s")
    print(f"端到端合计:            {ingest_s + refine_total:.1f}s")
    print(f"\n[FULL REPORT] -> {out_md}")
    print(f"[META]        -> {out_meta}")


if __name__ == "__main__":
    main()
