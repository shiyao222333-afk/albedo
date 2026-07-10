"""Albedo (Lian Zhen) · 内容摘要基础层 (A0)

中性"这篇讲什么"——不评级、不判真假，与 merits(评价)/assess(真假) 严格分离。
排在净化(C2)之后、评估(C3)之前，作为下游压缩上下文基底 + 报告开头。

决策（2026-07-10 锁定）：
  - gist: 1~2 句概括，语言跟原文（中进中出 / 英进英出）
  - bullets: 3~7 条要点
  - key_claims: 2~5 条"可被验证的主张"，中性提取，真假留给 assess
  - 降级 ①：原文 < 50 字 → 跳过 LLM，gist=原文，bullets/key_claims 留空
  - 降级 ②：LLM 失败 → gist=clean_text 前 200 字，bullets/key_claims 留空，绝不抛出中断流水线
  - 保质量优先（方案 X）：summary 只是"压缩底座"，A1/A2 仍读完整原文，不靠摘要替代原文
"""
from __future__ import annotations

from .llm import call_llm_json

_SKIP_LLM_LEN = 50          # 短于此字数跳过 LLM，直接原文当 gist
_FALLBACK_GIST_LEN = 200    # LLM 失败时 gist 取前 N 字
_MAX_BULLETS = 7            # bullets 上限
_MAX_KEY_CLAIMS = 5         # key_claims 上限


def _build_messages(clean_text: str, context: str) -> list:
    """构造 LLM 提问词：中性、不评价、语言跟原文。"""
    sys_msg = (
        "你是一个内容摘要助手。请阅读用户提供的文本，产出中性摘要。\n"
        "严格要求：\n"
        "1. 只提炼原文已有的信息，绝不评价、绝不判断真假、绝不添加原文没有的内容。\n"
        "2. 输出语言必须与原文保持一致（原文中文→中文，原文英文→英文）。\n"
        "3. gist 是 1~2 句话概括全文主旨；bullets 是 3~7 条关键要点；"
        "key_claims 是 2~5 条原文中'可被事实验证的主张'（如数据、方法、结论），同样不评判真假。"
    )
    user_parts = [f"待摘要文本：\n{clean_text}"]
    if context and context.strip():
        user_parts.append(f"补充背景（仅辅助理解，不改变原文信息）：\n{context.strip()}")
    user_parts.append(
        "请严格只输出如下 JSON，不要任何额外说明：\n"
        '{"gist": "1~2句概括（与原文同语言）", '
        '"bullets": ["要点1", "要点2", "..."], '
        '"key_claims": ["可被验证的主张1", "可被验证的主张2", "..."]}'
    )
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def _coerce_list(value, max_n: int) -> list:
    """把 LLM 返回值规整成非空字符串列表，最多 max_n 条。"""
    if not isinstance(value, list):
        value = [value]
    out = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s)
        if len(out) >= max_n:
            break
    return out


def summarize_content(clean_text: str, context: str = "") -> dict:
    """对净化后文本产出中性摘要。

    参数:
        clean_text: 净化(C2)后的纯文本
        context: 可选补充背景（如标题/来源），仅辅助 LLM 理解，不参与评级

    返回:
        dict: {gist: str, bullets: [str], key_claims: [str]}
        任何异常都降级为安全字典，绝不抛出。
    """
    text = (clean_text or "").strip()

    # 降级 ①：空文本 / 超短文本，跳过 LLM
    if not text:
        return {"gist": "", "bullets": [], "key_claims": []}
    if len(text) < _SKIP_LLM_LEN:
        return {"gist": text, "bullets": [], "key_claims": []}

    try:
        data = call_llm_json(
            _build_messages(text, context),
            max_tokens=1024,
        )
        gist = (data.get("gist") or "").strip()
        bullets = _coerce_list(data.get("bullets"), _MAX_BULLETS)
        key_claims = _coerce_list(data.get("key_claims"), _MAX_KEY_CLAIMS)

        # gist 缺失兜底（仍失败时退回前 200 字）
        if not gist:
            gist = text[:_FALLBACK_GIST_LEN]
        return {"gist": gist, "bullets": bullets, "key_claims": key_claims}

    except Exception:
        # 降级 ②：LLM 调用或解析失败，gist 取前 200 字，其余留空
        return {
            "gist": text[:_FALLBACK_GIST_LEN],
            "bullets": [],
            "key_claims": [],
        }
