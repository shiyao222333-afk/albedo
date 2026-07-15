"""内容类型自动分类（内容线 #75）

根据标题 / AI摘要 / 字幕片段，判断视频主要给观众什么价值，路由到对应萃取模板。
- temperature=0 + 固定枚举 → 确定性输出（兼治"同输入结果不稳定"任务）
- 失败/无法判断 → 降级 unknown（走通用路径），不阻断主流程

类别（与内容线萃取模板一一对应）：
  tutorial      教程/操作类：教一步步完成某事（软件教学、做菜、操作演示）
  tool_review   工具测评/介绍类：评测或介绍某工具/产品（开箱、对比、推荐）
  knowledge     知识科普类：解释概念/原理/机制（含干货讲解）
  opinion       观点评论类：表达观点、评论、点评（影评、时评、吐槽）
  entertainment 纯娱乐类：无信息增量（无信息吃播、搞笑、ASMR、纯猎奇）
  narrative     叙事故事类：以故事/vlog/经历为主
  unknown       无法判断（走通用路径）
"""
from __future__ import annotations

from core.llm import call_llm_json

CONTENT_TYPES = [
    "tutorial", "tool_review", "knowledge", "opinion",
    "entertainment", "narrative", "unknown",
]

_SYSTEM = """你是视频内容分类器。判断一条视频主要给观众什么价值，从以下类别中选唯一一个：
- tutorial: 教程/操作类，教观众一步步完成某件事（如软件教学、做菜、操作演示）
- tool_review: 工具测评/介绍类，评测或介绍某工具/产品（开箱、对比、推荐）
- knowledge: 知识科普类，解释概念、原理、机制（含干货讲解）
- opinion: 观点评论类，表达作者观点、评论、点评（影评、时评、吐槽）
- entertainment: 纯娱乐类，无信息增量（无信息吃播、搞笑、ASMR、纯猎奇）
- narrative: 叙事故事类，以故事/vlog/经历为主
- unknown: 无法判断

只输出 JSON：{"content_type":"<类别>"}，类别必须是上述之一。不要任何解释。"""


def classify_content_type(
    title: str = "",
    subtitle_lines: list = None,
    ai_conclusion: str = "",
    llm_kwargs: dict = None,
) -> str:
    """返回内容类型字符串；失败/无法判断降级 'unknown'。"""
    subtitle_lines = subtitle_lines or []
    sample = "\n".join(
        f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subtitle_lines[:40]
    )
    user = f"标题：{title}\n\nAI摘要：{ai_conclusion}\n\n字幕片段：\n{sample}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": user}],
            **(llm_kwargs or {}),
        )
        ct = (data.get("content_type") or "unknown").strip().lower()
        return ct if ct in CONTENT_TYPES else "unknown"
    except Exception:
        return "unknown"
