"""真实视频 3× 鲁棒性测试运行器（v0.4.3 验收）。

载入字幕样本（scripts/fetch_bilibili_subs.py 产出，或用户粘贴的 Nigredo 中转 .md / subtitle_lines JSON），
对同一输入跑 refine() 3 次，比对：
  - claim_quotes 集合（缓存生效应完全一致）
  - truth_label / status / trust_score（D-S 确定性应稳定）
报告各轮结论 + 落盘 data/out/<vid>_run{1,2,3}_report.md。

用法：python scripts/run_robustness_test.py <subtitle_lines.json> [--no-cache] [--shared-cache] [--model=...] [--max-tokens=...]
注意：
  - 默认（无 flag）：轮间独立 —— 每轮跑前清掉该视频 claims 缓存，三轮各自重新抽主张（烧 3 倍 key），
    但单轮内部 cache_enabled=True，走生产缓存代码路径（用户要求：轮间无缓存、轮内有缓存）。
  - --shared-cache：三轮共享缓存（2/3 轮命中缓存不重抽），仅验证"缓存冻结后稳定性"。
  - --no-cache：完全关闭缓存（含单轮内），调试退化模式用。
  - --model=XXX：临时切换模型（不改 .env），如 --model=deepseek-v4-flash。
  - --max-tokens=N：临时抬高所有 LLM 调用的 max_tokens 上限（见 core/llm.py 的
    ALBEDO_LLM_MAX_TOKENS_OVERRIDE），供推理模型（v4-flash 等会先"隐藏思考"吃掉预算）
    对照测试用，例如 --model=deepseek-v4-flash --max-tokens=8000。
  - 模型对照：方案1 = deepseek-chat（默认，快/确定/零推理开销）；方案2 = deepseek-v4-flash + 大预算
    （质量对照，未来比效果）。两种均可一键切换，不改代码。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

# ── 模型 / 预算覆盖（须在 import core 前设置：core.llm 在 import 时读 KB_LLM_MODEL）──
# 仅测试对照用：--model=deepseek-chat（默认走 .env）/ --max-tokens=8000（推理模型对照，见 core/llm.py）
for _a in sys.argv[1:]:
    if _a.startswith("--model="):
        os.environ["KB_LLM_MODEL"] = _a.split("=", 1)[1]
    elif _a.startswith("--max-tokens="):
        os.environ["ALBEDO_LLM_MAX_TOKENS_OVERRIDE"] = _a.split("=", 1)[1]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import nltk
except Exception:
    nltk = None  # 沙箱/venv 可能未装 nltk，punkt 缺失时由下方正则兜底

from core.models import AlbedoInput
from flows.refine import refine


def _ensure_punkt():
    """MiniCheck 内部用 nltk.sent_tokenize 分句。沙箱无 punkt 且外部下载被 pathsec 拦截时，
    用轻量正则分句兜底（本测试字幕已是短句，功能等价）。用户本机装有 punkt 时不触发。"""
    try:
        nltk.data.find("tokenizers/punkt")
        return  # punkt 可用，无需兜底
    except Exception:
        pass

    _re = re.compile(r"(?<=[。！？!?；;])")

    def _split(text):
        parts = _re.split(text or "")
        return [p.strip() for p in parts if p and p.strip()]

    try:
        import minicheck.inference as mi
        mi.sent_tokenize = _split
    except Exception:
        pass
    if nltk is not None:
        try:
            nltk.tokenize.sent_tokenize = _split  # type: ignore[assignment]
        except Exception:
            pass
    print("[punkt 兜底] 已用正则分句替代 nltk punkt（沙箱无 punkt 且无法下载）")


def _vid_from_path(path: str) -> str:
    """从文件名推导 BV 号（如 BV1h1LD6BELK_subs.json → BV1h1LD6BELK），无则空。
    确保字幕 JSON 未显式带 video_id 时，CE4 缓存仍可凭文件名定位、生效。"""
    m = re.search(r"(BV[0-9A-Za-z]+)", os.path.basename(path))
    return m.group(1) if m else ""


def load_input(path: str) -> AlbedoInput:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    vid = d.get("video_id") or _vid_from_path(path)
    if "subtitle_lines" in d:
        subs = d["subtitle_lines"]
        text = d.get("text") or "\n".join(s.get("text", "") for s in subs)
        return AlbedoInput(
            text=text, text_type="subtitle",
            video_id=vid, title=d.get("title", ""),
            up_name=d.get("up_name", ""), source_url=d.get("source_url", ""),
            subtitle_lines=subs,
        )
    # 退化：纯文本
    return AlbedoInput(text=d.get("text", ""), text_type=d.get("text_type", "subtitle"),
                        video_id=vid, title=d.get("title", ""))


def _clear_claim_cache(vid: str):
    """每轮跑前清掉该视频的 claims 缓存文件，确保三轮之间不共享缓存、
    每轮独立重抽（用户要求：轮间无缓存）。但单轮内 cache_enabled 仍开启，走生产缓存代码路径。"""
    if not vid or vid == "UNKNOWN":
        return
    p = os.path.join("cache", f"{vid}.claims.json")
    try:
        if os.path.exists(p):
            os.remove(p)
            print(f"[cache] 已清 {p}（本轮将从零重抽，不与上轮共享）")
    except Exception as e:
        print(f"[cache] 清 {p} 失败：{e}")


def run(path: str, use_cache: bool = True, independent: bool = True):
    inp = load_input(path)
    vid = inp.video_id or "UNKNOWN"
    print(f"=== 鲁棒性测试：{vid} | {inp.title} | 单轮缓存={use_cache} | 轮间独立={independent} ===")
    runs = []
    for i in range(1, 4):
        if independent:
            _clear_claim_cache(vid)  # 轮间清缓存：下一轮不复用上一轮冻结主张
        t0 = time.time()
        out = refine(inp, llm_kwargs={}, cache_enabled=use_cache)
        dt = time.time() - t0
        quotes = [c.get("quote", "") for c in out.claim_verifications]
        label = out.quality.truthfulness.label
        status = out.status
        trust = out.trust_score
        n = len(out.claim_verifications)
        print(f"RUN{i}: claims={n} label={label} status={status} trust={trust:.2f} "
              f"grounded={sum(1 for c in out.claim_verifications if c.get('faithfulness')=='grounded')} "
              f"({dt:.1f}s)")
        runs.append({"claims": out.claim_verifications, "quotes": quotes, "label": label,
                     "status": status, "trust": trust, "report": out.report, "n": n})
        # 落报告
        os.makedirs("data/out", exist_ok=True)
        with open(f"data/out/{vid}_run{i}_report.md", "w", encoding="utf-8") as f:
            f.write(out.report)

    # 比对（完整主张指纹：quote + accuracy + confidence，不能只比 quote）
    def _claim_fp(r):
        return tuple(sorted(
            f"{c.get('quote','')}::{c.get('accuracy','')}::{c.get('confidence',0)}"
            for c in r["claims"]
        ))
    fps = [_claim_fp(r) for r in runs]
    quotes_stable = len(set(fps)) == 1
    labels = [r["label"] for r in runs]
    label_stable = len(set(labels)) == 1
    print("\n--- 验收 ---")
    print(f"claims 完整一致(含验真结论,缓存冻结): {quotes_stable}")
    print(f"truth_label 稳定: {label_stable}  -> {labels}")
    print(f"status 稳定: {len(set(r['status'] for r in runs)) == 1}  -> {[r['status'] for r in runs]}")
    print(f"trust_score: {[round(r['trust'],2) for r in runs]}")
    print("\nRESULT:", "PASS" if (quotes_stable and label_stable) else "CHECK")
    # 打印 RUN1 报告前若干行供查看
    print("\n=== RUN1 报告预览（前 40 行）===")
    print("\n".join(runs[0]["report"].splitlines()[:40]))


if __name__ == "__main__":
    _pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not _pos:
        print("用法：python scripts/run_robustness_test.py <subtitle_lines.json> "
              "[--no-cache] [--shared-cache] [--model=...] [--max-tokens=...]")
        sys.exit(1)
    use_cache = "--no-cache" not in sys.argv
    # 默认轮间独立（每轮清缓存→三轮各自重抽）；--shared-cache 则三轮共享缓存（仅验缓存冻结稳定性）
    independent = "--shared-cache" not in sys.argv
    _ensure_punkt()  # 沙箱无 punkt 时兜底，确保 MiniCheck 真跑
    run(_pos[0], use_cache=use_cache, independent=independent)
