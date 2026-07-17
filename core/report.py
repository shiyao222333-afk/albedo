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

# 验真环节绝对化骗局话术标签 → 中文（与 truth_track._RED_FLAGS 对应）
_TRUTH_RED_FLAG_CN = {
    "zero_basis_income": "零基础高收益承诺",
    "guarantee": "保本/保过/稳赚话术",
    "quick_result": "极短时间见效承诺",
    "miracle_claim": "暴富/躺赚类奇迹宣称",
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


def _fact_cn(v: str) -> str:
    return {"factual": "事实", "opinion": "观点", "mixed": "混合"}.get(_str(v), _str(v) or "—")


def _scope_cn(v: str) -> str:
    return {"personal": "个人经验", "public": "公开断言"}.get(_str(v), _str(v) or "—")


def _grade_cn(grade: str) -> str:
    return {
        "L1": "L1 仅作者声称（无外部证据）",
        "L2": "L2 单源弱证据（截图 / 个例）",
        "L3": "L3 多源一致 / 权威来源",
        "L4": "L4 可验证事实 / 公认可复现",
    }.get(_str(grade), _str(grade) or "—")


# 形式线：钩子类型 → 中文
_HOOK_CN = {
    "question": "提问式",
    "shock": "震惊式",
    "statement": "断言式",
    "personal_story": "亲身故事式",
    "contrarian": "反直觉式",
    "value_promise": "价值承诺式",
    "curiosity_gap": "悬念缺口式",
    "other": "其他",
}


def _hook_cn(v: str) -> str:
    return _HOOK_CN.get(_str(v), _str(v) or "—")


def _content_score(o: dict) -> float:
    """干货度（内容价值轴 0-1，AC3：按锚定通过条目数计，避免虚高）。

    有字幕依据的可萃取条目越多 → 干货度越高；纯娱乐固定低。
    卖课教程（tutorial + 卖货意图）不高抬干货度（促销内容不夸大可照搬价值）。
    """
    ct = _str(o.get("content_type"))
    if ct == "entertainment":
        return 0.3
    ce = o.get("content_extract") or {}
    meta = (ce.get("_meta") or {}) if isinstance(ce, dict) else {}
    intent = meta.get("intent") or []
    # 锚定通过的抽取条目数（有依据 = 真干货）
    anchored = 0
    if isinstance(ce, dict):
        if ct == "tutorial":
            g = ce.get("_gate") or {}
            if g.get("checked"):
                anchored = g.get("checked", 0) - g.get("dropped", 0)
            else:
                anchored = len(ce.get("steps", []) or []) + len(ce.get("preconditions", []) or [])
        elif ct == "opinion":
            anchored = len(ce.get("evidence", []) or [])
        elif ct == "knowledge":
            anchored = len(ce.get("example", []) or [])
        elif ct == "tool_review":
            anchored = len(ce.get("pros", []) or []) + len(ce.get("cons", []) or [])
        elif ct == "narrative":
            anchored = len(ce.get("sections", []) or [])
    # 无结构化萃取 → 看摘要
    if anchored == 0:
        s = o.get("summary") or {}
        if isinstance(s, dict) and (s.get("bullets") or s.get("gist")):
            return 0.6
        return 0.4
    # 干货度随锚定条目数增长，封顶 1.0
    score = min(1.0, 0.25 + 0.1 * anchored)
    # 卖课教程不高抬干货度（AC3：促销内容不夸大可照搬价值）
    if ct == "tutorial" and "卖货" in intent:
        score = min(score, 0.6)
    return round(score, 2)


# ── 各章节渲染 ──
def _render_verdict_card(out: dict) -> str:
    """结论卡：三轴总览（干货度 / 自洽置信 / 表达力）+ 真实性结论 + 证据分级 + 入库状态 + 变现标注。"""
    q = out.get("quality") or {}
    t = q.get("truthfulness") or {}
    label = _truth_label_cn(t.get("label"))
    raw_grade = _str(t.get("evidence_grade"))
    grade = _grade_cn(raw_grade)
    score = t.get("score")
    score_txt = f"{score}" if isinstance(score, (int, float)) and score else ""
    # AF1：非"外部已验证"的"真实"→标注为视频自洽·待外部核实，
    # 涵盖 MiniCheck 本地字幕核验 / 仅主张自洽（均未联网外部核查）两种情形。
    if label == "真实" and _str(t.get("verification_level")) != "externally_verified":
        label_disp = "真实（视频自洽·待外部核实）"
    else:
        label_disp = label

    status = _status_cn(out.get("status"))

    trust = out.get("trust_score")
    trust_txt = f"{trust}" if isinstance(trust, (int, float)) and trust else "—"
    # 三轴（v0.4.0 形式线加入表达力；干货度由内容萃取派生；自洽置信来自验真融合）
    content_axis = _content_score(out)
    form_axis = out.get("form_score")
    form_txt = f"{form_axis}" if isinstance(form_axis, (int, float)) and form_axis else "—"
    self_conf = (score / 100.0) if isinstance(score, (int, float)) and score else 0.0

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
        f"- **真实性结论**：{label_disp}" + (f"（自洽置信 {score_txt}/100）" if score_txt else ""),
        f"- **证据分级**：{grade}",
        f"- **深度验真（Layer2）**：{('已启用（L4 mDeBERTa-XNLI 本地字幕核验）' if raw_grade == 'L4' else '未启用（L1，仅不联网快筛——结论为「未验真」默认值，不代表真实或虚假）')}",
        f"- **入库状态**：{status}",
        # AF2：三轴用统一的 0-1 自洽置信（来自验真融合），不再与 FPF 信任分混用"可信度"标签
        f"- **三轴总览**：干货度 {content_axis} ｜ 自洽置信 {self_conf:.2f} ｜ 表达力 {form_txt}",
        # FPF 信任分单独标注，明确"单源未联网深验·仅供参考"，避免与自洽置信打架
        f"- **入库信任分（FPF）**：{trust_txt}（单源未联网深验，仅供参考）",
        f"- **表达力（形式线）**：{form_txt}",
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


# ── 内容线渲染（字幕输入，content_type 非空时启用）──
_CT_LABEL = {
    "tutorial": "教程 / 操作类 · 可照搬 SOP",
    "tool_review": "工具测评 · 决策参考",
    "opinion": "观点评论 · 论点图",
    "knowledge": "知识科普 · 概念卡",
    "entertainment": "纯娱乐 · 转形式线",
    "narrative": "叙事故事 · 大纲",
    "generic": "通用要点",
}


def _ts_item(item):
    """把 {text, ts} 或纯字符串渲染成带时间戳的列表项；空则 None。
    AC5：若 item 含 '_ungrounded'（锚定闸门判定字幕无依据）→ 追加 ⚠️ 标记。
    """
    if isinstance(item, dict):
        txt = _str(item.get("text"))
        ts = _str(item.get("ts"))
        flag = " ⚠️字幕无依据" if item.get("_ungrounded") else ""
    else:
        txt = _str(item)
        ts = ""
        flag = ""
    if not txt:
        return None
    return f"- {txt}{flag}" + (f" （{ts}）" if ts else "")


def _render_content_summary(o: dict) -> str:
    """内容线摘要：gist + bullets，每条带来源 ts；无原文支撑的标 ⚠️。"""
    s = o.get("summary") or {}
    gist = _str(s.get("gist"))
    bullets = s.get("bullets") or []
    grounding = o.get("grounding") or {}
    ungrounded = grounding.get("ungrounded") or []
    ug_texts = {_str(u.get("text")) for u in ungrounded}
    lines = ["## 📌 内容摘要（讲什么 · 措辞可变 · 内容锚定字幕）", ""]
    if not (gist or bullets):
        return "\n".join(lines + [_DEG, ""])
    if gist:
        lines += [f"> {gist}", ""]
    if bullets:
        lines += ["**要点：**"]
        for b in bullets:
            if isinstance(b, dict):
                txt = _str(b.get("text"))
                ts = _str(b.get("source_ts"))
            else:
                txt = _str(b)
                ts = ""
            flag = " ⚠️无原文支撑" if txt in ug_texts else ""
            suffix = f" （{ts}）" if ts else ""
            lines.append(f"- {txt}{suffix}{flag}")
        lines += [""]
    checked = grounding.get("checked")
    if checked:
        lines += [f"_保真自检：{checked} 句已核对，{len(ungrounded)} 句无原文支撑_", ""]
    return "\n".join(lines)


def _render_content_extract(o: dict) -> str:
    """按 content_type 渲染对应萃取卡片（tutorial/tool_review/opinion/knowledge/...）。"""
    ct = _str(o.get("content_type")) or "generic"
    ce = o.get("content_extract") or {}
    label = _CT_LABEL.get(ct, ct)
    lines = [f"## 🧩 内容萃取（{label}）", ""]
    # AC2/AC3：含卖货/揭秘曝光意图 → 顶部声明，提醒勿盲目照搬/轻信
    if isinstance(ce, dict):
        intent = (ce.get("_meta") or {}).get("intent") or []
        if "卖货" in intent or "揭秘曝光" in intent:
            tags = "、".join(t for t in intent if t in ("卖货", "揭秘曝光"))
            lines += [f"> ⚠️ **该视频含[{tags}]意图**：以下萃取仅供参照，关键操作/主张请独立核实，"
                      f"勿盲目照搬或轻信。", ""]
    if not ce:
        return "\n".join(lines + [_DEG, ""])

    if ct == "tutorial":
        purpose = _str(ce.get("purpose"))
        if purpose:
            lines += [f"**目的**：{purpose}", ""]
        for title, key in (("前置条件", "preconditions"), ("步骤", "steps"),
                           ("注意事项 / 坑", "warnings"), ("完成判定", "completion_checklist")):
            items = [_ts_item(x) for x in (ce.get(key) or [])]
            items = [x for x in items if x]
            if items:
                lines += [f"**{title}：**"] + items + [""]
        # AC5 锚定闸门结果：被剔除的编造步骤
        gate = ce.get("_gate") or {}
        if gate.get("dropped"):
            lines += [f"> ⚠️ **锚定闸门剔除 {gate['dropped']} 条字幕无依据的编造步骤**"
                      f"（时间戳/文本在真实字幕中找不到依据，已自动移除，避免误导「可照搬」）", ""]
        return "\n".join(lines)

    if ct == "tool_review":
        for title, key in (("优点", "pros"), ("缺点", "cons")):
            items = [_ts_item(x) for x in (ce.get(key) or [])]
            items = [x for x in items if x]
            if items:
                lines += [f"**{title}：**"] + items + [""]
        concl = _str(ce.get("conclusion"))
        if concl:
            lines += [f"**结论**：{concl}", ""]
        bf = _str(ce.get("best_for"))
        if bf:
            lines += [f"**适合**：{bf}", ""]
        return "\n".join(lines)

    if ct == "opinion":
        claim = _str(ce.get("claim"))
        if claim:
            lines += [f"**核心主张**：{claim}", ""]
        ev = [_ts_item(x) for x in (ce.get("evidence") or [])]
        ev = [x for x in ev if x]
        if ev:
            lines += ["**论据：**"] + ev + [""]
        stance = _str(ce.get("stance"))
        if stance:
            lines += [f"**立场**：{stance}", ""]
        counter = [_ts_item(x) for x in (ce.get("counter") or [])]
        counter = [x for x in counter if x]
        if counter:
            lines += ["**反驳的相反观点：**"] + counter + [""]
        # AC5 锚定闸门：论据/反驳无字幕依据 → 标 ⚠️（见上逐条）
        gate = ce.get("_gate") or {}
        if gate.get("flagged"):
            lines += [f"> ⚠️ 锚定闸门标记 {gate['flagged']} 条论据/反驳在字幕中无依据（保留供你核对，不删除）", ""]
        return "\n".join(lines)

    if ct == "knowledge":
        concept = _str(ce.get("concept"))
        if concept:
            lines += [f"**概念**：{concept}", ""]
        dfn = _str(ce.get("definition"))
        if dfn:
            lines += [f"**定义**：{dfn}", ""]
        ex = [_ts_item(x) for x in (ce.get("example") or [])]
        ex = [x for x in ex if x]
        if ex:
            lines += ["**例子：**"] + ex + [""]
        return "\n".join(lines)

    if ct == "entertainment":
        note = _str(ce.get("note")) or "纯娱乐内容，内容线无可萃取信息；其价值在形式 / 表达线。"
        return "\n".join(lines + [f"> {note}", ""])

    if ct == "narrative":
        ov = _str(ce.get("overview"))
        if ov:
            lines += [ov, ""]
        for sec in (ce.get("sections") or []):
            if not isinstance(sec, dict):
                continue
            ts = _str(sec.get("ts"))
            sub = _str(sec.get("subtitle"))
            uflag = " ⚠️字幕无依据" if sec.get("_ungrounded") else ""
            lines.append(f"### {sub}{uflag}" + (f" （{ts}）" if ts else ""))
            pts = _list(sec.get("points"))
            if pts:
                lines += [f"- {p}" for p in pts]
            lines += [""]
        gate = ce.get("_gate") or {}
        if gate.get("flagged"):
            lines += [f"> ⚠️ 锚定闸门标记 {gate['flagged']} 个段落标题/要点在字幕中无依据（保留供你核对，不删除）", ""]
        return "\n".join(lines)

    # generic
    gist = _str(ce.get("gist"))
    if gist:
        lines += [f"> {gist}", ""]
    kp = [_ts_item(x) for x in (ce.get("key_points") or [])]
    kp = [x for x in kp if x]
    if kp:
        lines += ["**关键要点：**"] + kp + [""]
    return "\n".join(lines)


def _render_key_sentences(o: dict) -> str:
    """关键原话兜底（Route A 原文不动，供你核对摘要没丢东西）。"""
    ks = o.get("key_sentences") or []
    lines = ["## 📝 关键原话（兜底 · 原文不动）", ""]
    if not ks:
        return "\n".join(lines + [_DEG, ""])
    for k in ks:
        if not isinstance(k, dict):
            continue
        ts = _str(k.get("ts"))
        txt = _str(k.get("text"))
        if txt:
            lines.append(f"- [{ts}] {txt}" if ts else f"- {txt}")
    lines += [""]
    return "\n".join(lines)


def _render_highlight_blocks(o: dict) -> str:
    """高光上下文块：高光点 + 前后 ±15 条字幕 + 邻近弹幕。"""
    blocks = o.get("highlight_blocks") or []
    lines = ["## ✨ 高光上下文块（高光 ±15 条字幕 + 弹幕）", ""]
    if not blocks:
        return "\n".join(lines + ["（未提供高光数据——输入无高光时间点，非分析失败）", ""])
    for b in blocks:
        if not isinstance(b, dict):
            continue
        ts = _str(b.get("ts"))
        content = _str(b.get("content"))
        lines += [f"### 高光 {ts}：{content}" if ts else "### 高光", ""]
        subs = b.get("subtitle_window") or []
        if subs:
            lines += ["字幕窗口："]
            for s in subs:
                if isinstance(s, dict):
                    st = _str(s.get("ts"))
                    txt = _str(s.get("text"))
                    lines.append(f"- [{st}] {txt}" if st else f"- {txt}")
            lines += [""]
        dms = b.get("danmaku") or []
        if dms:
            lines += ["弹幕：" + " / ".join(_str(d.get("text")) for d in dms[:10]
                                            if isinstance(d, dict))]
            lines += [""]
    return "\n".join(lines)


# ── 验真逐条渲染（v0.3.0）──
def _render_truth_track(o: dict) -> str:
    """逐条验真章节：每条断言显示原话+ts+事实/观点+个人/公开+判定+话术/矛盾标记。
    Layer0.5 剔除的无原文支撑断言不出现在列表（仅在总览计 dropped）。
    """
    tt = o.get("truth_track") or {}
    claims = o.get("claim_verifications") or []
    lines = ["## 🛡️ 逐条验真（真 / 假 / 可疑）", ""]
    if not claims and not tt:
        return "\n".join(lines + [_DEG, ""])

    n = tt.get("n_claims", len(claims))
    dropped = tt.get("n_dropped", 0)
    sev = _str(tt.get("severity", "ok"))
    trust = tt.get("trust_score")
    sev_cn = {
        "alert": "⚠️ 检出视频自相矛盾（严重存疑）",
        "warn": "⚠️ 检出绝对化话术（存疑）",
        "ok": "暂未检出明确矛盾 / 话术",
    }.get(sev, "")
    lines.append(f"- 抽取断言 **{n}** 条（Layer0.5 防瞎编剔除 {dropped} 条无原文支撑）")
    if isinstance(trust, (int, float)):
        lines.append(f"- 校准可信度（保守，未联网深验）：{trust}")
    if sev_cn:
        lines.append(f"- 信号：{sev_cn}")
    if tt.get("recency_note"):
        lines.append(f"- 时效：{tt['recency_note']}")
    if tt.get("is_personal"):
        lines.append("- 含第一人称经验主张（不可外部证伪，按内部自洽采纳）")
    lines.append("")

    for c in claims:
        quote = _str(c.get("quote"))
        if not quote:
            continue
        ts = _str(c.get("ts"))
        badges = []
        fac = _str(c.get("factuality"))
        scope = _str(c.get("scope"))
        if fac:
            badges.append(_fact_cn(fac))
        if scope:
            badges.append(_scope_cn(scope))
        head = f"- [{ts}] {quote}" if ts else f"- {quote}"
        if badges:
            head += f"  `({' / '.join(badges)})`"
        lines.append(head)

        notes = []
        if _str(c.get("accuracy")) == "contradicted":
            notes.append("⚠️ **视频自相矛盾**")
        if c.get("red_flags"):
            flags = "、".join(_TRUTH_RED_FLAG_CN.get(f, _str(f)) for f in c["red_flags"])
            notes.append(f"⚠️ 绝对化话术：{flags}")
        if c.get("weasel_flag"):
            notes.append("💧 含水词（无出处权威暗示，谨慎采信）")
        hl = c.get("hedge_level", 0) or 0
        if hl >= 2:
            notes.append("🌫️ 强模糊语（低承诺，可赖账）")
        elif hl == 1:
            notes.append("～ 弱保留语")
        if _str(c.get("accuracy")) == "unverified":
            notes.append("❓ 未联网深验（默认未验证，非假）")
        if notes:
            lines.append("  - " + "；".join(notes))

    contradictions = tt.get("contradictions") or []
    if contradictions:
        lines.append("")
        lines.append("**自相矛盾对：**")
        for cx in contradictions:
            lines.append(
                f"- 断言 {cx.get('claim_id')}（{cx.get('ts', '')}） ⇄ "
                f"断言 {cx.get('with_claim_id')}（{cx.get('with_ts', '')}）"
            )

    # ── 被过滤主张审计（v0.4.9 F 任务）：硬删过滤器留痕，误杀可追溯 ──
    dropped_audit = tt.get("dropped_audit") or []
    if dropped_audit:
        lines.append("")
        lines.append("**🔍 被过滤主张（审计 · 如误杀请告诉我，我调阈值）：**")
        _stage_cn = {
            "AE1_water": "AE1 水词/过渡句",
            "AE1_noncheckworthy": "AE1 非可证伪(观点/主观)",
            "L0.5_ungrounded": "Layer0.5 防瞎编(字幕无依据)",
        }
        for d in dropped_audit:
            _stage = _stage_cn.get(d.get("stage", ""), d.get("stage", ""))
            _q = _str(d.get("quote"))
            _ts = _str(d.get("ts"))
            _r = _str(d.get("reason"))
            _head = f"- [{_stage}] {_q}" if not _ts else f"- [{_stage}] [{_ts}] {_q}"
            lines.append(_head)
            if _r:
                lines.append(f"  - 原因：{_r}")
    lines.append("")
    return "\n".join(lines)


# ── 形式线渲染（v0.4.0, Track B）──
_FORM_WEAK_NOTE = "弱代理信号（非真实留存曲线；受播放量/话题/平台文化影响）"


def _render_form_track(o: dict) -> str:
    """🎬 形式分析章节：钩子 / 叙事结构 / 人设 / 修辞话术 / 可复制模板 / 情绪代理 / 说服强度 / 保真自检。
    所有视频类型都渲染（教程出教学结构、娱乐出故事骨架）。
    """
    ft = o.get("form_track") or {}
    if not ft:
        return "\n".join(["## 🎬 形式分析（怎么讲的）", "", _DEG, ""])
    # AD3：钩子/叙事段若被形式保真自检(form_faithfulness)标 ungrounded，
    # 渲染时打 ⚠️，不伪装成权威原句/真实时间戳。
    _faith = ft.get("form_faithfulness") or {}
    _ug = _faith.get("ungrounded") or []
    _ug_hook = {_str(u.get("text")) for u in _ug if u.get("what") == "hook_text"}
    _ug_seg_ts = {_str(u.get("text")) for u in _ug if u.get("what") == "segment_ts"}

    lines = ["## 🎬 形式分析（怎么讲的 · Track B）", ""]

    # 钩子
    hook = ft.get("hook") or {}
    ht = _str(hook.get("hook_type"))
    if ht or hook.get("hook_text"):
        strength = hook.get("strength", 0) or 0
        hts = f"{_hook_cn(ht)}（强度 {strength}/5）" if ht else f"强度 {strength}/5"
        lines.append(f"- **开场钩子**：{hts}")
        htext = _str(hook.get("hook_text"))
        if htext:
            flag = " ⚠️ 非逐字/无字幕依据" if htext in _ug_hook else ""
            lines.append(f"  - 钩子原句：{htext}" + (f" （{hook.get('ts','')}）" if hook.get("ts") else "") + flag)
        lines.append("")

    # 节奏（纯函数）
    pac = ft.get("pacing") or {}
    if pac:
        tier_cn = {"short": "短视频(<3分钟)", "mid": "中视频(3-15分钟)", "long": "长视频(>15分钟)", "unknown": "未知"}
        lines.append(
            f"- **节奏**：{tier_cn.get(_str(pac.get('length_tier')), _str(pac.get('length_tier')))}｜"
            f"语速 {pac.get('speech_rate_wpm', 0)} 字/分｜停顿 {pac.get('pause_count', 0)} 次"
            f"（均 {pac.get('avg_pause_s', 0)} 秒）"
        )
        lines.append("")

    # 叙事结构
    segs = ft.get("narrative_segments") or []
    if segs:
        lines.append("**叙事结构：**")
        for s in segs:
            if not isinstance(s, dict):
                continue
            ts = _str(s.get("ts"))
            title = _str(s.get("title"))
            purpose = _str(s.get("purpose"))
            head = f"- {title}" + (f" （{ts}）" if ts else "")
            if ts and ts in _ug_seg_ts:
                head += " ⚠️ 时间戳无字幕依据（段落可能为LLM推断）"
            lines.append(head)
            if purpose:
                lines.append(f"  - 这节干嘛：{purpose}")
        lines.append("")

    # 人设
    persona = ft.get("persona") or {}
    if persona.get("trust_base") or persona.get("perspective") or persona.get("tags"):
        lines.append("**人设：**")
        if persona.get("trust_base"):
            lines.append(f"- 信任基石：{_str(persona.get('trust_base'))}")
        if persona.get("perspective"):
            lines.append(f"- 视角：{_str(persona.get('perspective'))}")
        tags = persona.get("tags") or []
        if tags:
            lines.append(f"- 标签：{'、'.join(_str(t) for t in tags)}")
        lines.append("")

    # 修辞话术
    devs = ft.get("rhetoric_devices") or []
    if devs:
        lines.append("**修辞话术（说服技巧）：**")
        for d in devs:
            if not isinstance(d, dict):
                continue
            t = _str(d.get("type"))
            span = _str(d.get("span_text"))
            ts = _str(d.get("ts"))
            item = f"- {t}"
            if span:
                item += f"：{span}"
            if ts:
                item += f" （{ts}）"
            lines.append(item)
        lines.append("")

    # 可复制模板（机器可读，供凝华消费）
    tpl = ft.get("reusable_template") or {}
    if tpl.get("title_formula") or tpl.get("section_skeleton") or tpl.get("persona_tags"):
        lines.append("**可复制骨架（供下游自动生成脚本消费）：**")
        if tpl.get("title_formula"):
            lines.append(f"- 标题公式：{_str(tpl.get('title_formula'))}")
        sk = tpl.get("section_skeleton") or []
        if sk:
            lines.append("- 段落骨架：")
            for s in sk:
                if not isinstance(s, dict):
                    continue
                ts = _str(s.get("ts"))
                purpose = _str(s.get("purpose"))
                lines.append(f"  - {purpose}" + (f" （{ts}）" if ts else ""))
        pt = tpl.get("persona_tags") or []
        if pt:
            lines.append(f"- 人设标签：{'、'.join(_str(t) for t in pt)}")
        lines.append("")

    # 情绪曲线（弹幕弱代理）
    emo = ft.get("emotion_proxy") or {}
    if emo:
        tl = emo.get("timeline") or []
        note = _str(emo.get("note"))
        if tl:
            lines.append(f"- **情绪/留存代理**：弹幕密度时间轴 {len(tl)} 段（{_FORM_WEAK_NOTE}）")
        elif note:
            lines.append(f"- **情绪/留存代理**：{note}")
        lines.append("")

    # 说服包装强度（G1 反向桥）
    polish = ft.get("persuasion_polish")
    if isinstance(polish, (int, float)):
        if polish >= 0.7:
            desc, note = "高包装", "（高包装+未验证证据→验真线已额外谨慎）"
        elif polish >= 0.4:
            desc, note = "中包装", "（包装适中，未验证证据仍请自行判断）"
        else:
            desc, note = "低包装", "（包装较轻，未验证证据仍请自行判断）"
        lines.append(f"- **说服包装强度**：{polish}（{desc}{note}）")
        lines.append("")

    # 形式保真自检（G2）
    faith = ft.get("form_faithfulness") or {}
    checked = faith.get("checked")
    if checked:
        ug = faith.get("ungrounded") or []
        if ug:
            lines.append(f"_形式保真自检：{checked} 项已核对，{len(ug)} 项无字幕依据（{', '.join(_str(u.get('text',''))[:30] for u in ug)}）_")
        else:
            lines.append(f"_形式保真自检：{checked} 项已核对，均能在字幕找到依据_")
        lines.append("")

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
    if o.get("content_type"):
        # 内容线（字幕输入）：按内容类型渲染，带关键原话兜底 / 高光块 / 保真标注
        sections = [
            _render_verdict_card(o),
            _render_truth_track(o),
            _render_form_track(o),
            _render_content_summary(o),
            _render_content_extract(o),
            _render_key_sentences(o),
            _render_highlight_blocks(o),
            _render_provenance(o, i),
            _render_numeric(o),
        ]
    else:
        # 旧通用路径（非字幕输入）
        sections = [
            _render_verdict_card(o),
            _render_truth_track(o),
            _render_form_track(o),
            _render_summary(o),
            _render_merits(o),
            _render_structure(o),
            _render_provenance(o, i),
            _render_numeric(o),
        ]
    return "\n".join(head + sections).rstrip() + "\n"
