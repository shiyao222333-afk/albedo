"""Albedo (Lian Zhen) · 质量评估 (T3 / C3)

合并实现 v0.1.0 三项评估能力：
  - #688 真实性评估：nuwa 三重验证（来源可核验 / 逻辑自洽 / 证据强度）
         + anyone-skill L1-L4 证据分级；LLM 单源评估 → Truthfulness 四维。
  - #690 数值自洽校验：轻量规则抽取文本中数值断言，检测过度承诺与内部数值矛盾，
         作为真实性格的补充证据（不直接落盘，注入 Prompt 辅助判定）。
  - #691 变现检测：复用 purify.detect_sales_features() 判定 monetization.related + category，
         护栏「变现 ≠ 差内容」（ADR-005），不因在卖课就直接判 false。

对外暴露：
  - assess_truthfulness(clean_text, *, context=None, numeric_hint=None) -> Truthfulness
  - check_numeric_consistency(text) -> NumericCheck   (#690)
  - assess_monetization(clean_text) -> Monetization    (#691)
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# 注：call_llm_json 改为 assess_truthfulness() 内惰性导入，
# 使本模块在缺 requests 的环境下也可被导入（数值/变现检测不依赖 LLM）。
from core.models import Monetization, Truthfulness
from core.purify import detect_sales_features


# ───────────────────────────────────────────────────────────────────────────
# #688 真实性评估 Prompt（nuwa 三重验证 + anyone-skill L1-L4 证据分级）
# ───────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "你是内容真实性鉴定师，隶属于「炼真(Albedo)」认知精炼流水线。"
    "你的唯一任务是判断给定内容中知识性主张的真实程度，并给出证据分级。"
    "保持客观，严格区分「个人经验分享」与「可证伪的事实主张」。"
    "重要护栏：内容涉及变现（卖课 / 带货 / 付费工具）不等于虚假——"
    "卖课话术是你评估的**证据之一**，但不能仅凭「在卖课」就判 false。"
)

_USER_TEMPLATE = """【待鉴定内容】
{clean_text}

【上下文（可选）】
来源平台：{platform}
作者：{up_name}
标题：{title}

【三重验证框架】（请依次在脑中执行，reasoning 中引用结论）
1. 来源可核验性：内容是否给出可独立验证的信息、出处或具体可查证的事实？还是仅作者口头声称？
2. 逻辑自洽性：内容内部是否存在前后矛盾、因果不成立，或常见伪科学 / 骗局特征
   （如永动机、稳赚不赔、零基础月入十万、包教包会必成功）？
3. 证据强度：主张的支撑证据属于哪一级（见下方 L1-L4）。

【证据分级 L1-L4（anyone-skill 标准）】
- L1：仅作者声称，无任何外部证据
- L2：单源弱证据（截图、单一匿名个例）
- L3：多源一致证据或权威来源引用
- L4：可验证事实、公认可复现、常识级正确

【数值自洽补充校验】（由规则引擎预检，供你参考，非最终结论）
{numeric_hint}

【输出要求】
仅输出一个 JSON 对象，不要任何解释性文字，格式严格如下：
{{
  "label": "true" | "false" | "suspect",
  "score": 0-100 的整数（越高越可信）,
  "reasoning": "中文，2-4 句，说明判定依据，引用具体证据或破绽",
  "evidence_grade": "L1" | "L2" | "L3" | "L4"
}}
判定指引：
- 核心事实可被 L3/L4 证据支撑且无逻辑矛盾 → true（score 偏高）
- 明确与可验证事实矛盾、或属典型骗局 / 伪科学 → false（score 偏低）
- 证据不足无法定论、含过度承诺话术、或逻辑存疑但无法定论 → suspect（score 居中）
"""


def _coerce_label(v: str) -> str:
    v = (v or "").strip().lower()
    if v in ("true", "false", "suspect"):
        return v
    return "suspect"  # 最保守默认


def _coerce_grade(v: str) -> str:
    v = (v or "").strip().upper()
    if v in ("L1", "L2", "L3", "L4"):
        return v
    return "L1"


def _coerce_score(v) -> int:
    try:
        s = int(round(float(v)))
    except (TypeError, ValueError):
        return 50
    return max(0, min(100, s))


# 自一致性投票次数：仅在 LLM 真正尊重 seed（如本地 Ollama）时才能提升稳定性。
# DeepSeek(deepseek-v4-flash) 对复杂判定不尊重 seed，3 票在边界内容上仍是 50/50，投了也白投。
# 故默认单调用（不浪费开销）；将来接通确定性模型时，调用方传 n_votes=3+ 即可启用投票。
_N_TRUTH_VOTES = 1


def assess_truthfulness(
    clean_text: str,
    *,
    context: Optional[dict] = None,
    numeric_hint: Optional[str] = None,
    n_votes: int = None,
    **llm_kwargs,
) -> Truthfulness:
    """调用 LLM 对净化后文本做真实性评估，返回 Truthfulness 四维。

    采用自一致性投票（self-consistency majority voting）抑制 LLM 残留非确定性：
    对同一输入发起 n_votes 次调用（每次 seed 固定递增 0,1,2...），对 label 取多数票；
    score 取多数票簇均值、evidence_grade 取多数票簇众数、reasoning 取簇内首个。
    因 seed 固定，跨 run 结果完全可复现，质检关卡不再随随机性漂移。

    context: 可选 {platform, up_name, title} 等上下文，用于辅助判定。
    numeric_hint: 由 check_numeric_consistency() 生成的补充校验文本，注入 Prompt。
    n_votes: 投票次数（默认 _N_TRUTH_VOTES；≥1，1 退化为单次调用）。
    llm_kwargs: 可透传 base_url / api_key / model 给 LLM 调用（便于测试）。
    """
    ctx = context or {}
    from core.llm import call_llm_json  # 惰性导入：仅在调用 LLM 时需要 requests
    user_msg = _USER_TEMPLATE.format(
        clean_text=(clean_text or "").strip() or "（空内容）",
        platform=ctx.get("platform", "未知"),
        up_name=ctx.get("up_name", "未知"),
        title=ctx.get("title", "未知"),
        numeric_hint=numeric_hint or "（未提供数值校验信息）",
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # 种子由投票循环统一控制，移除调用方可能误传的 seed
    llm_kwargs.pop("seed", None)
    n = max(1, int(n_votes) if n_votes is not None else _N_TRUTH_VOTES)

    results = []
    for i in range(n):
        try:
            data = call_llm_json(messages, seed=i, **llm_kwargs)
        except RuntimeError:
            # 单次调用失败不应让整次评估崩掉，跳过该剧投票
            continue
        results.append({
            "label": _coerce_label(data.get("label")),
            "score": _coerce_score(data.get("score")),
            "reasoning": (data.get("reasoning") or "").strip(),
            "evidence_grade": _coerce_grade(data.get("evidence_grade")),
        })

    if not results:
        # 全部调用失败 → 最保守兜底
        return Truthfulness(
            label="suspect",
            score=50,
            reasoning="真实性评估 LLM 调用全部失败，已按最保守策略兜底为「存疑」。",
            evidence_grade="L1",
        )

    # label 多数票（Counter 平票时保留先插入项，因 seed 固定故结果可复现）
    label_votes = Counter(r["label"] for r in results)
    majority_label, _ = label_votes.most_common(1)[0]

    # 多数票簇内聚合：score 均值、grade 众数、reasoning 取簇内首个
    cluster = [r for r in results if r["label"] == majority_label]
    avg_score = round(sum(r["score"] for r in cluster) / len(cluster))
    grade_votes = Counter(r["evidence_grade"] for r in cluster)
    majority_grade, _ = grade_votes.most_common(1)[0]
    majority_reasoning = cluster[0]["reasoning"]

    return Truthfulness(
        label=majority_label,
        score=avg_score,
        reasoning=majority_reasoning,
        evidence_grade=majority_grade,
    )


# ───────────────────────────────────────────────────────────────────────────
# #690 数值自洽统计校验（轻量规则，作为真实性格补充证据）
# ───────────────────────────────────────────────────────────────────────────
@dataclass
class NumericCheck:
    """数值自洽校验结果（不入数据契约，仅供 Prompt 注入 / 调试）。"""
    flags: list = field(default_factory=list)          # 过度承诺 / 红色信号标签
    contradictions: list = field(default_factory=list) # 同维度数值矛盾
    claims: list = field(default_factory=list)         # 抽取到的数值断言 (dimension, value)
    summary: str = ""                                  # 供 LLM 注入的一句话摘要

    def to_hint(self) -> str:
        if not self.flags and not self.contradictions and not self.claims:
            return "未发现明显数值过度承诺或内部矛盾。"
        lines = []
        if self.flags:
            lines.append("红色信号：" + "；".join(self.flags))
        if self.contradictions:
            lines.append("数值矛盾：" + "；".join(self.contradictions))
        if self.claims:
            claims_txt = "，".join(f"{d}={v}" for d, v in self.claims)
            lines.append("已抽取数值断言：" + claims_txt)
        return "\n".join(lines)


# 维度数值抽取：捕捉「关键词 + 数字 + 单位」形式的断言
_NUM_PATTERNS = [
    ("income", re.compile(r"(月入|收入|赚[到得]?|收益|到手|日薪|时薪)\s*[^0-9]{0,6}?(\d+(?:\.\d+)?)\s*(万|千|w|元|块|美元|￥|\$)?")),
    ("time_to_result", re.compile(r"(\d+(?:\.\d+)?)\s*(天|周|个月|月|小时|分钟)\s*(?:内|就|可|能|便|左右)*\s*(?:见效|学会|出单|回本|赚钱|赚到)")),
    ("percentage", re.compile(r"(\d+(?:\.\d+)?)\s*%(?:的)?\s*(?:通过率|有效|成功率|增长|准确率|转正|达成)")),
    ("follower", re.compile(r"(\d+(?:\.\d+)?)\s*(万|千|w)?\s*(粉丝|关注|播放|阅读)")),
]

# 过度承诺 / 骗局红色信号
_RED_FLAGS = [
    ("zero_basis_income", re.compile(r"零基础.{0,8}月入\s*\d+\s*万|月入\s*\d+\s*万.{0,8}零基础|小白.{0,8}月入\s*\d+\s*万")),
    ("guarantee", re.compile(r"(保证.{0,4}(赚|回本|过)|百分百|稳赚|包过|包教包会|稳赚不赔|躺赚)")),
    ("quick_result", re.compile(r"(\d+(?:\.\d+)?)\s*(天|周)\s*(?:内|就|可|能|便|左右)*\s*(?:见效|学会|出单|回本|赚)")),
    ("miracle_claim", re.compile(r"(永动机|一夜暴富|轻松月入|被动收入.{0,6}(万|元)|睡后收入)")),
]

# 轻量中文数字归一化（覆盖常见个位数 + 十），便于 \d 模式抽取
# 注意：刻意不含「零」——避免把「零基础」误改成「0基础」破坏 red flag 字面匹配
_CN_NUM = {
    "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
}


def _normalize_chinese_numerals(text: str) -> str:
    """把常见中文数字替换为阿拉伯数字（MVP 仅做字符级替换，不做复杂量词换算）。"""
    return "".join(_CN_NUM.get(ch, ch) for ch in text)


def check_numeric_consistency(text: str) -> NumericCheck:
    """轻量数值自洽校验：抽取数值断言、检测过度承诺与内部矛盾。

    注意：本函数是规则启发式，结果仅供真实性评估参考，不是终审结论。
    """
    if not text:
        return NumericCheck(summary="（空内容，无数值可校验）")
    # 剥离字幕时间戳 [mm:ss] / [mm:ss.xx]，避免把时间戳分钟数当成数值断言
    # （如 "[02:08]" 的 02 被 income 正则误判为收入）——竞品 vergex 同思路（解析前剥离时间戳）
    text = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", " ", text)
    text = _normalize_chinese_numerals(text)

    flags: list = []
    contradictions: list = []
    claims: list = []

    # 1) 数值维度抽取，记录每个维度的取值集合
    dim_values: dict = {}
    for dim, pat in _NUM_PATTERNS:
        for m in pat.finditer(text):
            if dim == "time_to_result":
                val = m.group(1) + m.group(2)
            elif dim == "percentage":
                val = m.group(1) + "%"
            else:
                # income / follower：数字 + 可选单位
                num = m.group(2)
                unit = m.group(3) or ""
                val = num + unit
            claims.append((dim, val))
            dim_values.setdefault(dim, set()).add(val)

    # 2) 同维度出现不同取值 → 内部数值矛盾
    for dim, vals in dim_values.items():
        if len(vals) > 1:
            contradictions.append(f"{dim} 出现不一致数值：{' / '.join(sorted(vals))}")

    # 3) 红色信号（过度承诺 / 骗局特征）
    for label, pat in _RED_FLAGS:
        if pat.search(text):
            flags.append(label)

    result = NumericCheck(flags=flags, contradictions=contradictions, claims=claims)
    result.summary = result.to_hint()
    return result


# ───────────────────────────────────────────────────────────────────────────
# #691 变现检测（复用卖课话术特征 + 护栏：变现 ≠ 差内容）
# ───────────────────────────────────────────────────────────────────────────
# 变现类别关键词（在命中付费诱导基础上细分「在卖什么」）
_CATEGORY_KEYWORDS = {
    "selling_course": ["课程", "训练营", "课", "教学", "学费", "报名", "资料包",
                        "包教包会", "听课", "直播课", "网课"],
    "ecommerce": ["下单", "购买", "商品", "带货", "橱窗", "同款", "链接", "拍下",
                  "购物车", "好物"],
    "tool_paid": ["工具", "软件", "插件", "会员", "付费", "订阅", "授权", "脚本"],
    "other": ["私信", "加微信", "扫码", "领取资料", "咨询", "了解详情"],
}


def classify_monetization_category(text: str, features: list) -> str:
    """根据命中的卖课特征 + 关键词细分变现类别。"""
    if not features:
        return ""
    # 优先级：卖课 > 电商 > 付费工具 > 其他诱导
    for cat in ("selling_course", "ecommerce", "tool_paid", "other"):
        kws = _CATEGORY_KEYWORDS[cat]
        if any(kw in text for kw in kws):
            return cat
    return "other"


def assess_monetization(clean_text: str) -> Monetization:
    """判定内容是否涉及变现及其类别。

    护栏（ADR-005）：related=True 仅表示「内容在卖什么」，不构成真实性结论；
    绝不因此直接判 false。note 记录卖课特征与类别，供报告展示。
    """
    features = detect_sales_features(clean_text or "")
    if not features:
        return Monetization(related=False, category="", note="")

    category = classify_monetization_category(clean_text or "", features)
    # 中文特征名映射，便于报告阅读
    feat_cn = {
        "over_promise": "过度承诺",
        "vague_pressure": "模糊施压",
        "paid_induce": "付费诱导",
        "fake_authority": "伪权威",
    }
    feat_txt = "、".join(feat_cn.get(f, f) for f in features)
    cat_cn = {
        "selling_course": "卖课/知识付费",
        "ecommerce": "电商带货",
        "tool_paid": "付费工具/软件",
        "other": "其他付费诱导",
        "": "",
    }.get(category, category)
    note = f"检测到变现特征：{feat_txt}；类别：{cat_cn}（仅标注，不因此判假）"
    return Monetization(related=True, category=category, note=note)
