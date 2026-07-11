"""Albedo (Lian Zhen) · 鉴定报告渲染 (A4)

render_report(out, inp) -> str：从精炼结果渲染人读 Markdown 报告（主交付物，ADR-004 单报告）。

章节序（A4 决策）：结论卡 → A0 摘要 → 优点(8 子能力) → 结构化(SOP/大纲) → 溯源 → 数值预检。
任何维度降级留空 → 显 "（该维度未能生成）" 不崩。
语言：章节标签固定中文（UI 语言）；正文内容由上游 LLM 按原文语言产出，此处不翻译。

设计要点：
  - 输入通吃 dataclass / dict（out 可传 RefinedKnowledgeObject 或其 to_dict()；inp 作溯源兜底）。
  - 数值预检复用 core.assess.check_numeric_consistency（纯规则、无 LLM、确定性）；
    v0.2.0 assess.py 冻结不改动，故报告内数值预检段在此重算（不入数据契约）。
  - 本模块不触发任何 LLM，可纯逻辑单测。
"""
from __future__ import annotations

import dataclasses
from datetime import datetime

from core.assess import check_numeric_consistency


_DEG = "（该维度未能生成）"   # 降级占位：某维度未能产出时显示

# 数值预检红色信号英文标签 → 中文（让报告"说人话"；维度名 income/time_to_result 等已可读，不改）
_RED_FLAG_CN = {
    "zero_basis_income": "零基础高收益承诺",
    "guarantee": "保本 / 保过 / 稳赚话术",
    "quick_result": "极短时间见效承诺",
    "miracle_claim": "暴富 / 躺赚类奇迹宣称",
}


# ── 输入归一化：dataclass / dict 通吃 ──
def _to_dict(obj):
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _list(v) -> list:
    if not isinstance(v, list):
        v = [v] if v not in (None, "", []) else []
    return [str(x).strip() for x in v if str(x).strip()]


def _truth_label_cn(label: str) -> str:
    return {"true": "真实", "false": "虚假", "suspect": "存疑"}.get(_str(label), _str(label) or "未知")


def _status_cn(status: str) -> str:
    return {
        "accepted": "建议入库",
        "suspect": "存疑待核",
        "rejected": "不建议入库（判定不实）",
    }.get(_str(status), _str(status) or "未知")


def _grade_cn(grade: str) -> str:
    return {
        "L1": "L1 仅作者声称（无外部证据）",
        "L2": "L2 单源弱证据（截图 / 个例）",
        "L3": "L3 多源一致 / 权威来源",
        "L4": "L4 可验证事实 / 公认可复现",
    }.get(_str(grade), _str(grade) or "—")


# ── 各章节渲染 ──
def _render_verdict_card(out: dict) -> str:
    """结论卡：真实性结论 + 证据分级 + 入库状态 + 可信度 + 变现标注（护栏：仅标注不判假）。"""
    q = out.get("quality") or {}
    t = q.get("truthfulness") or {}
    label = _truth_label_cn(t.get("label"))
    score = _str(t.get("score"))
    grade = _grade_cn(t.get("evidence_grade"))
    status = _status_cn(out.get("status"))

    trust = out.get("trust_score")
    trust_txt = f"{trust}" if isinstance(trust, (int, float)) and trust else "—"

    mon = out.get("monetization") or {}
    if mon.get("related"):
        cat_cn = {
            "selling_course": "卖课 / 知识付费",
            "ecommerce": "电商带货",
            "tool_paid": "付费工具 / 软件",
            "other": "其他付费诱导",
            "": "—",
        }.get(_str(mon.get("category")), _str(mon.get("category")) or "—")
        mon_txt = f"涉及变现（{cat_cn}）— 仅标注，不因此判假"
    else:
        mon_txt = "未检出明显变现"

    return "\n".join([
        "## 🧾 结论卡",
        "",
        f"- **真实性结论**：{label}" + (f"（置信 {score}/100）" if score else ""),
        f"- **证据分级**：{grade}",
        f"- **入库状态**：{status}",
        f"- **可信度（FPF）**：{trust_txt}",
        f"- **变现标注**：{mon_txt}",
        "",
    ])


def _render_summary(out: dict) -> str:
    """A0 摘要：gist / bullets / key_claims（中性"讲什么"，与真假严格分离）。"""
    s = out.get("summary") or {}
    gist = _str(s.get("gist"))
    bullets = _list(s.get("bullets"))
    claims = _list(s.get("key_claims"))
    lines = ["## 📌 内容摘要（讲了什么）", ""]
    if not (gist or bullets or claims):
        return "\n".join(lines + [_DEG, ""])
    if gist:
        lines += [f"> {gist}", ""]
    if bullets:
        lines += ["**要点：**"] + [f"- {b}" for b in bullets] + [""]
    if claims:
        lines += ["**关键主张（待你验证真假）：**"] + [f"- {c}" for c in claims] + [""]
    return "\n".join(lines)


def _render_merits(out: dict) -> str:
    """优点分析：8 子能力（内容轴 6 + 形式轴 2）。整块空才降级。"""
    m = out.get("merits") or {}
    lines = ["## 💡 优点分析（8 子能力）", ""]
    if not m:
        return "\n".join(lines + [_DEG, ""])

    def block(title, val):
        if isinstance(val, list):
            items = _list(val)
            if not items:
                return []
            return [f"**{title}：**"] + [f"- {x}" for x in items] + [""]
        sv = _str(val)
        if not sv:
            return []
        return [f"**{title}：** {sv}", ""]

    lines += block("方法价值 · 核心洞察", m.get("core_insight"))
    lines += block("可照搬步骤", m.get("reusable_steps"))
    lines += block("差异化亮点", m.get("differentiation"))
    lines += block("陷阱预警", m.get("pitfalls"))
    lines += block("适用场景", m.get("applicable_scenarios"))
    lines += block("迁移成本", m.get("migration_cost"))

    # 形式轴：两个 dict 子能力，渲染为子列表（值可为字符串或字符串列表）
    for title, key in (("表达形式质量（形式轴）", "presentation_craft"),
                        ("格式可复用（形式轴）", "format_reusable")):
        sub = m.get(key)
        if isinstance(sub, dict) and sub:
            lines += [f"**{title}：**", ""]
            for k, v in sub.items():
                if isinstance(v, list):
                    items = _list(v)
                    if not items:
                        continue
                    lines += [f"- {k}："] + [f"  - {x}" for x in items]
                else:
                    sv = _str(v)
                    if sv:
                        lines += [f"- {k}：{sv}"]
            lines += [""]
    return "\n".join(lines)


def _render_structure(out: dict) -> str:
    """结构化提炼：sop 型 → SOP；其余 → 大纲（按 structure_type 路由）。sop/outline 互斥。"""
    stype = _str(out.get("structure_type"))
    lines = ["## 🧩 结构化提炼", ""]

    if stype == "sop":
        sop = out.get("sop") or {}
        if not any([
            _str(sop.get("purpose")),
            _list(sop.get("preconditions")),
            sop.get("steps"),
            _list(sop.get("warnings")),
            _list(sop.get("completion_checklist")),
        ]):
            return "\n".join(lines + [_DEG, ""])
        lines += ["> 结构类型：**SOP（可照做的标准流程）**", ""]
        purpose = _str(sop.get("purpose"))
        if purpose:
            lines += [f"**目的**：{purpose}", ""]
        pre = _list(sop.get("preconditions"))
        if pre:
            lines += ["**前置条件**："] + [f"- {x}" for x in pre] + [""]
        steps = sop.get("steps") or []
        if isinstance(steps, list) and steps:
            lines += ["**步骤**："]
            for s in steps:
                if isinstance(s, dict):
                    idx = s.get("idx")
                    txt = _str(s.get("text"))
                    prefix = f"{idx}. " if idx is not None else "- "
                    lines.append(f"{prefix}{txt}")
                else:
                    lines.append(f"- {_str(s)}")
            lines += [""]
        warns = _list(sop.get("warnings"))
        if warns:
            lines += ["**注意事项 / 坑**："] + [f"- {x}" for x in warns] + [""]
        chk = _list(sop.get("completion_checklist"))
        if chk:
            lines += ["**完成判定**："] + [f"- {x}" for x in chk] + [""]
        return "\n".join(lines)

    # 非 sop：大纲（argument/case_study/comparison/narrative/qa/mixed/unknown）
    outline = out.get("outline") or {}
    overview = _str(outline.get("overview"))
    sections = outline.get("sections") or []
    if not (overview or sections):
        return "\n".join(lines + [_DEG, ""])
    label = stype or "unknown"
    lines += [f"> 结构类型：**{label}（按大纲组织）**", ""]
    if overview:
        lines += [overview, ""]
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sub = _str(sec.get("subtitle"))
            pts = _list(sec.get("points"))
            if sub:
                lines.append(f"### {sub}")
            if pts:
                lines += [f"- {p}" for p in pts] + [""]
    return "\n".join(lines)


def _render_provenance(out: dict, inp: dict) -> str:
    """溯源：provenance 优先，缺字段回退 inp。整块空才降级。"""
    prov = out.get("provenance") or {}

    def pick(*keys):
        for k in keys:
            v = _str(prov.get(k)) or _str(inp.get(k))
            if v:
                return v
        return ""

    vid = pick("video_id")
    up = pick("up_name")
    url = pick("source_url")
    title = pick("title")
    processed = pick("processed_at")
    lines = ["## 🔗 溯源", ""]
    if not (vid or up or url or title or processed):
        return "\n".join(lines + [_DEG, ""])
    if title:
        lines += [f"- 标题：{title}"]
    if up:
        lines += [f"- 作者 / UP：{up}"]
    if vid:
        lines += [f"- 来源 ID：{vid}"]
    if url:
        lines += [f"- 来源链接：{url}"]
    if processed:
        lines += [f"- 精炼时间：{processed}"]
    lines += [""]
    return "\n".join(lines)


def _render_numeric(out: dict) -> str:
    """数值自洽预检：复用 check_numeric_consistency（纯规则）。无 clean_text 才降级。"""
    clean = _str(out.get("clean_text"))
    lines = ["## 🔢 数值自洽预检（真实性补充证据）", ""]
    if not clean:
        return "\n".join(lines + [_DEG, ""])
    nc = check_numeric_consistency(clean)
    if nc.flags:
        flags_cn = "；".join(_RED_FLAG_CN.get(_str(f), _str(f)) for f in nc.flags)
        lines += [f"- 红色信号：{flags_cn}"]
    if nc.contradictions:
        lines += ["- 数值矛盾：" + "；".join(_str(c) for c in nc.contradictions)]
    if nc.claims:
        lines += ["- 抽取断言：" + "，".join(f"{d}={v}" for d, v in nc.claims)]
    if not (nc.flags or nc.contradictions or nc.claims):
        lines += ["- 未发现明显数值过度承诺或内部矛盾。"]
    lines += [""]
    return "\n".join(lines)


# ── A4 编排主入口 ──
def render_report(out, inp=None) -> str:
    """渲染人读 Markdown 鉴定报告（ADR-004 单报告，主交付物）。

    参数:
        out: RefinedKnowledgeObject（dataclass）或其 dict（to_dict() 结果）
        inp: AlbedoInput（dataclass）或其 dict；仅作溯源兜底（provenance 优先）
    返回:
        str: 完整 Markdown 报告
    """
    o = _to_dict(out)
    i = _to_dict(inp) if inp is not None else {}

    head = [
        "# 🔬 炼真鉴定报告 (Albedo)",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    sections = [
        _render_verdict_card(o),
        _render_summary(o),
        _render_merits(o),
        _render_structure(o),
        _render_provenance(o, i),
        _render_numeric(o),
    ]
    return "\n".join(head + sections).rstrip() + "\n"
