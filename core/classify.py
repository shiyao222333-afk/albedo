"""内容类型自动分类（内容线 #75 · v0.4.8 AC1 多轴重构）

旧版 classify_content_type 是单标签分类，会把"揭秘卖课"误判成 tutorial →
错误路由到 SOP 萃取 → LLM 编造 SOP（鲁棒性测试 run2/run3 致命问题）。

v0.4.8 改多轴分类：
  structure   : 主萃取模板（单选）→ 决定路由到哪个萃取器
  intent[]    : 视频目的（多选）→ 影响卖家声明/信任/干货度（AC2/AC3 消费）
  monetization: 视频本身是否以变现/推销为目的（bool）

关键：揭秘/曝光/劝退类（如"揭秘某卖课套路"）即使演示了对方操作，
      其 structure 必须是 opinion（主结构是评说），绝不能是 tutorial。
- temperature=0 + 固定枚举 → 确定性输出
- 失败/无法判断 → 降级 unknown（走通用路径），不阻断主流程
"""
from __future__ import annotations

from core.llm import call_llm_json

STRUCTURE_TYPES = [
    "tutorial", "tool_review", "knowledge", "opinion",
    "entertainment", "narrative", "unknown",
]
INTENT_TYPES = [
    "教学", "卖货", "揭秘曝光", "评测", "科普", "吐槽", "讲故事", "娱乐",
]

_SYSTEM = """你是视频内容多维分类器。请同时判断三个维度（不要只取一个标签）：

1) structure（结构/主萃取模板，单选）：这条视频主要给观众什么"可萃取的信息结构"？
   - tutorial: 教观众一步步完成某事（操作演示、做菜、软件教学）
   - tool_review: 评测/介绍某工具产品（开箱、对比、推荐）
   - knowledge: 解释概念/原理/机制（干货科普）
   - opinion: 表达观点/评论/点评/揭秘/吐槽/劝退（影评、时评、揭秘卖课、避坑警告）
   - entertainment: 纯娱乐无信息增量（搞笑、ASMR、无信息吃播）
   - narrative: 以故事/vlog/亲身经历为主
   - unknown: 无法判断
   重要：揭秘/曝光/劝退类（如"揭秘某卖课套路""避坑指南"）即使演示了对方的操作步骤，
         其主结构是 opinion（在评说/警告），不是 tutorial（不是在教你做）。

2) intent[]（目的，可多选）：这条视频想达成什么？
   - 教学: 真心教观众掌握技能
   - 卖货: 视频本身在推销/带货/推课（自身变现）
   - 揭秘曝光: 揭穿/曝光某套路或真相
   - 评测: 客观评测对比
   - 科普: 传播知识
   - 吐槽: 情绪化批评/调侃
   - 讲故事: 分享经历
   - 娱乐: 逗乐

3) monetization（bool）：视频本身是否以变现/推销为目的（卖货/推课/带货引流）。

只输出 JSON（不要解释）：
{"structure":"<单选>","intent":["<可多选>"],"monetization":true/false}"""


def classify_content(
    title: str = "",
    subtitle_lines: list = None,
    ai_conclusion: str = "",
    llm_kwargs: dict = None,
) -> dict:
    """多轴分类。返回 {structure, intent:[], monetization:bool}；失败降级 unknown/[]/False。"""
    subtitle_lines = subtitle_lines or []
    sample = "\n".join(
        f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subtitle_lines[:40]
    )
    user = f"标题：{title}\n\nAI摘要：{ai_conclusion}\n\n字幕片段：\n{sample}"
    fallback = {"structure": "unknown", "intent": [], "monetization": False}
    try:
        data = call_llm_json(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": user}],
            **(llm_kwargs or {}),
        )
        structure = _str(data.get("structure")).lower()
        if structure not in STRUCTURE_TYPES:
            structure = "unknown"
        intent = [_str(i) for i in (data.get("intent") or []) if _str(i) in INTENT_TYPES]
        monet = bool(data.get("monetization", False))
        return {"structure": structure, "intent": intent, "monetization": monet}
    except Exception:
        return fallback


def classify_content_type(
    title: str = "",
    subtitle_lines: list = None,
    ai_conclusion: str = "",
    llm_kwargs: dict = None,
) -> str:
    """向后兼容：返回 structure 单标签；失败/无法判断降级 'unknown'。"""
    return classify_content(title, subtitle_lines, ai_conclusion, llm_kwargs).get("structure", "unknown")


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()
