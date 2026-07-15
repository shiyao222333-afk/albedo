"""摘要保真自检（#79 类 SummaC NLI）

检查"改写后的摘要"是否被字幕原文支撑，揪出模型可能编造的句。
注意区分：这是「总结是否编造」（忠实性），不是「视频说的是不是真话」（验真，
由 assess.py 另管，本轮不动）。

做法：把每条 summary bullet + 全部字幕原文一次性送 LLM，逐条判断 supported（蕴含）。
返回 {checked, ungrounded:[{text, ts}]}，ungrounded 即在报告里标"⚠️无原文支撑"。

确定性：call_llm_json（temperature=0）。降级：检查失败 → {checked:0, ungrounded:[]}。
"""
from __future__ import annotations

from core.llm import call_llm_json

_SYSTEM = """你是摘要忠实性检查器。给定一组"摘要要点"和"视频字幕原文"，
对每条摘要要点判断：它陈述的事实/观点是否能被字幕原文直接支撑（蕴含）？
- supported=true：字幕里有对应内容，或可由字幕合理推出
- supported=false：字幕里找不到任何依据，疑似编造/臆测

只输出 JSON（不要解释）：
{
  "results": [
    {"text":"<摘要要点原文>", "supported": true/false},
    ...
  ]
}"""


def check_grounding(
    summary_bullets: list,
    subtitle_lines: list,
    llm_kwargs: dict = None,
) -> dict:
    """summary_bullets: list[{text, source_ts}]；subtitle_lines: 字幕原文。

    返回 {checked, ungrounded:[{text, ts}]}。
    """
    bullets = [b for b in (summary_bullets or []) if isinstance(b, dict) and b.get("text")]
    if not bullets:
        return {"checked": 0, "ungrounded": []}

    subs = "\n".join(
        f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subtitle_lines
    )
    bullets_text = "\n".join(f"{i+1}. {b['text']}" for i, b in enumerate(bullets))
    user = f"字幕原文：\n{subs}\n\n待检查摘要要点：\n{bullets_text}"

    try:
        data = call_llm_json(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=2000,
            **(llm_kwargs or {}),
        )
        results = data.get("results") or []
        ungrounded = []
        for r in results:
            if not r.get("supported", True):
                # 反查 ts（按 text 匹配回原 bullet）
                src = next((b.get("source_ts", "") for b in bullets
                            if b["text"] == r.get("text")), "")
                ungrounded.append({"text": r.get("text", ""), "ts": src})
        return {"checked": len(results), "ungrounded": ungrounded}
    except Exception:
        # 降级：不标记任何为未支撑（宁漏不误杀），但记录未检查
        return {"checked": 0, "ungrounded": []}
