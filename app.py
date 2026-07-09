"""Albedo (Lian Zhen) · 最小 UI (v0.1.0)

Streamlit 界面：手动提交文件 / 馏析项目输出（best-effort）→ 一键炼真 →
展示净化文本 + 真实性（label/score/reasoning/evidence_grade）+ 入库状态 + 变现标注，
并支持导出 .md 报告与 .json 精炼对象。

启动：双击 run.bat（自动装依赖并开 http://localhost:8501）
依赖 LLM：需在 .env 配置 KB_LLM_API_KEY（对齐熔知约定）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import streamlit as st

from core.models import AlbedoInput
from flows.refine import refine
from core.assess import check_numeric_consistency

st.set_page_config(page_title="炼真 Albedo · 认知精炼", page_icon="🔬", layout="wide")


# ── 展示用中文映射 ──
_LABEL_CN = {"true": "✅ 真实", "false": "❌ 虚假", "suspect": "⚠️ 存疑"}
_STATUS_CN = {
    "accepted": ("✅ 建议入库", "success"),
    "suspect": ("⚠️ 存疑待核", "warning"),
    "rejected": ("❌ 判定不实 / 不建议入库", "error"),
}
_GRADE_CN = {
    "L1": "L1 仅作者声称（无外部证据）",
    "L2": "L2 单源弱证据（截图 / 个例）",
    "L3": "L3 多源一致 / 权威来源",
    "L4": "L4 可验证事实 / 公认可复现",
}
_CAT_CN = {
    "selling_course": "卖课 / 知识付费",
    "ecommerce": "电商带货",
    "tool_paid": "付费工具 / 软件",
    "other": "其他付费诱导",
    "": "—",
}


def _parse_nigredo_json(obj: dict) -> AlbedoInput:
    """宽松解析 Nigredo process() 输出为 AlbedoInput。

    兼容键：text/content/subtitle；meta 或顶层 title/up_name/source_url/video_id。
    """
    text = obj.get("text") or obj.get("content") or obj.get("subtitle") or ""
    meta = obj.get("meta") or {}
    return AlbedoInput(
        text=text,
        text_type=obj.get("text_type", "subtitle"),
        signals=obj.get("signals") or meta.get("signals") or {},
        video_id=obj.get("video_id") or meta.get("video_id") or "",
        title=obj.get("title") or meta.get("title") or "",
        up_name=obj.get("up_name") or meta.get("up_name") or "",
        source_url=obj.get("source_url") or meta.get("source_url") or "",
    )


def _best_effort_parse(raw: str):
    """馏析输出格式未定 → best-effort 解析。

    像 JSON（对象或含对象的数组）就返回 dict，否则原样返回纯文本字符串。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        data = json.loads(s)
    except Exception:
        return s
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
        return s
    if isinstance(data, dict):
        return data
    return s


def _build_report_md(out, inp: AlbedoInput) -> str:
    """把精炼结果渲染为可读 .md 报告。"""
    t = out.quality.truthfulness
    lines = [
        "# 炼真报告 (Albedo)",
        "",
        f"- 来源：{inp.title or '未知'} / {inp.up_name or '未知'}",
        f"- 入库状态：**{out.status}**",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 净化后文本",
        out.clean_text or "（空）",
        "",
        "## 真实性评估",
        f"- 结论：**{t.label}**（置信 {t.score}/100）",
        f"- 证据分级：{_GRADE_CN.get(t.evidence_grade, t.evidence_grade)}",
        f"- 判断依据：{t.reasoning or '（无）'}",
        "",
        "## 变现标注",
        f"- 是否涉及变现：{'是' if out.monetization.related else '否'}",
        f"- 类别：{_CAT_CN.get(out.monetization.category, out.monetization.category)}",
        f"- 说明：{out.monetization.note or '—'}",
        "",
        "## 数值自洽预检",
    ]
    nc = check_numeric_consistency(out.clean_text)
    if nc.flags:
        lines.append("- 红色信号：" + "；".join(nc.flags))
    if nc.contradictions:
        lines.append("- 数值矛盾：" + "；".join(nc.contradictions))
    if nc.claims:
        lines.append("- 抽取断言：" + "，".join(f"{d}={v}" for d, v in nc.claims))
    if not (nc.flags or nc.contradictions or nc.claims):
        lines.append("- 未发现明显数值过度承诺或内部矛盾。")
    return "\n".join(lines)


def main():
    st.title("🔬 炼真 (Albedo) · 认知精炼")
    st.caption(
        "流水线中段：净化 + 多维真实性评估 + 变现标注 → 入库就绪报告。"
        "验证标准：卖课谎言标「虚假/存疑」、真实教程标「真实」。"
    )

    with st.sidebar:
        st.subheader("ℹ️ 配置说明")
        st.info(
            "真实性评估需要 LLM。请在项目根 `.env` 配置：\n"
            "```\nKB_LLM_API_KEY=sk-...\nKB_LLM_BASE_URL=https://api.deepseek.com/v1\n"
            "KB_LLM_MODEL=deepseek-chat\n```\n（与熔知 KB_LLM_* 约定一致）"
        )

    mode = st.radio("输入方式", ["手动提交文件", "馏析项目输出"], horizontal=True)
    text_type = st.selectbox(
        "文本类型",
        ["subtitle", "social_post", "article", "doc_ppt", "doc_excel", "webpage"],
        index=0,
        help="subtitle=口语字幕走 ASR 清洗；其余仅做空白规整。馏析档若按 JSON 解析会沿用其自带类型。",
    )

    inp: AlbedoInput | None = None

    if mode == "手动提交文件":
        uploaded = st.file_uploader(
            "选择文本文件",
            type=["txt", "srt", "md", "text", "vtt", "json", "csv"],
            help="支持字幕 / 文章 / 帖子 / 文档等纯文本。",
        )
        pasted = st.text_area("或粘贴文本（兜底）", height=180,
                              placeholder="没有文件？直接把字幕 / 文章 / 帖子粘到这里…")
        title = st.text_input("标题（可选）", "")
        up_name = st.text_input("作者 / UP（可选）", "")
        content = ""
        if uploaded is not None:
            content = uploaded.read().decode("utf-8", "ignore")
            st.success(f"已读取文件：{uploaded.name}（{len(content)} 字）")
        elif pasted.strip():
            content = pasted
        if content.strip():
            inp = AlbedoInput(text=content, text_type=text_type,
                              title=title, up_name=up_name)
    else:
        uploaded = st.file_uploader(
            "选择馏析输出文件",
            type=["txt", "srt", "md", "json", "text", "vtt", "csv"],
            help="馏析输出格式未定：像 JSON 就结构化解析，否则当纯文本处理。",
        )
        pasted = st.text_area("或粘贴馏析输出（兜底）", height=180,
                              placeholder='{"text": "...", "meta": {"title": "..."}} 或直接粘纯文本')
        raw = ""
        if uploaded is not None:
            raw = uploaded.read().decode("utf-8", "ignore")
        elif pasted.strip():
            raw = pasted
        if raw.strip():
            parsed = _best_effort_parse(raw)
            if isinstance(parsed, dict):
                inp = _parse_nigredo_json(parsed)
                st.success(f"已按 JSON 结构化解析：{len(inp.text)} 字"
                           + (f"｜标题：{inp.title}" if inp.title else ""))
            else:
                inp = AlbedoInput(text=parsed, text_type=text_type)
                st.info("馏析输出非 JSON，已按纯文本处理。")

    if st.button("🚀 一键炼真", type="primary", disabled=(inp is None or not inp.text.strip())):
        with st.spinner("精炼中（调用 LLM 评估真实性）…"):
            try:
                out = refine(inp)
            except RuntimeError as e:
                st.error(f"评估失败：{e}\n\n请检查 .env 中的 KB_LLM_API_KEY 是否配置。")
                return
            except Exception as e:
                st.error(f"未预期错误：{e}")
                return

        # ── 结果展示 ──
        st.divider()
        status_cn, status_kind = _STATUS_CN.get(out.status, ("未知", "warning"))
        getattr(st, status_kind)(f"入库状态：{status_cn}（{out.status}）")

        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("🔎 真实性评估")
            t = out.quality.truthfulness
            st.markdown(f"**结论**：{_LABEL_CN.get(t.label, t.label)}（置信 {t.score}/100）")
            st.markdown(f"**证据分级**：{_GRADE_CN.get(t.evidence_grade, t.evidence_grade)}")
            st.markdown(f"**判断依据**：{t.reasoning or '（无）'}")
        with col2:
            st.subheader("💰 变现标注")
            if out.monetization.related:
                st.markdown(f"- 涉及变现：**是**")
                st.markdown(f"- 类别：{_CAT_CN.get(out.monetization.category, out.monetization.category)}")
                st.caption(out.monetization.note)
            else:
                st.markdown("- 涉及变现：**否**")

        st.subheader("🧹 净化后文本")
        st.text_area("", out.clean_text, height=180, disabled=True, label_visibility="collapsed")

        # ── 数值自洽预检（透明展示）──
        with st.expander("🔢 数值自洽预检（真实性补充证据）"):
            nc = check_numeric_consistency(out.clean_text)
            if nc.flags:
                st.write("红色信号：", "；".join(nc.flags))
            if nc.contradictions:
                st.write("数值矛盾：", "；".join(nc.contradictions))
            if nc.claims:
                st.write("抽取断言：", "，".join(f"{d}={v}" for d, v in nc.claims))
            if not (nc.flags or nc.contradictions or nc.claims):
                st.write("未发现明显数值过度承诺或内部矛盾。")

        # ── 导出 ──
        st.divider()
        st.subheader("📤 导出")
        vid = inp.video_id or hashlib.md5(inp.text.encode("utf-8")).hexdigest()[:10]
        md = _build_report_md(out, inp)
        js = out.to_json()
        c1, c2 = st.columns(2)
        c1.download_button("下载 .md 报告", md, file_name=f"albedo_{vid}.md", mime="text/markdown")
        c2.download_button("下载 .json 对象", js, file_name=f"albedo_{vid}.json",
                           mime="application/json")


if __name__ == "__main__":
    main()
