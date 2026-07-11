"""Albedo (Lian Zhen) · 最小 UI (v0.2.0)

Streamlit 界面：手动提交文件 / 馏析项目输出（best-effort）→ 一键炼真 →
直接渲染 A4 产出的完整鉴定报告（out.report），并支持导出 .md 报告与 .json 精炼对象。

启动：双击 run.bat（自动装依赖并开 http://localhost:8501）
依赖 LLM：需在 .env 配置 KB_LLM_API_KEY（对齐熔知约定）。
"""
from __future__ import annotations

import hashlib
import json

import streamlit as st

from core.models import AlbedoInput
from flows.refine import refine

st.set_page_config(page_title="炼真 Albedo · 认知精炼", page_icon="🔬", layout="wide")


# ── 展示用中文映射 ──
_LABEL_CN = {"true": "✅ 真实", "false": "❌ 虚假", "suspect": "⚠️ 存疑"}
_STATUS_CN = {
    "accepted": ("✅ 建议入库", "success"),
    "suspect": ("⚠️ 存疑待核", "warning"),
    "rejected": ("❌ 判定不实 / 不建议入库", "error"),
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


def main():
    st.title("🔬 炼真 (Albedo) · 认知精炼")
    st.caption(
        "流水线中段：净化 + 多维真实性评估 + 优点萃取 + 结构化 + 溯源 → 入库就绪鉴定报告。"
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
        with st.spinner("精炼中（调用 LLM 多维评估）…"):
            try:
                out = refine(inp)
            except RuntimeError as e:
                st.error(f"评估失败：{e}\n\n请检查 .env 中的 KB_LLM_API_KEY 是否配置。")
                return
            except Exception as e:
                st.error(f"未预期错误：{e}")
                return

        # ── 顶部结论卡（一眼概览）──
        st.divider()
        status_cn, status_kind = _STATUS_CN.get(out.status, ("未知", "warning"))
        getattr(st, status_kind)(f"入库状态：{status_cn}（{out.status}）")
        t = out.quality.truthfulness
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown(f"**真实性结论**：{_LABEL_CN.get(t.label, t.label)}（置信 {t.score}/100）")
        with col2:
            st.markdown(f"**信任分**：{out.trust_score:.2f}（0–1）")
        if out.monetization.related:
            st.caption(f"💰 涉及变现：{_CAT_CN.get(out.monetization.category, out.monetization.category)}"
                       f" — {out.monetization.note or '—'}")

        # ── 完整鉴定报告（主交付物，ADR-004 单报告）──
        st.divider()
        st.subheader("📋 鉴定报告")
        st.markdown(out.report)

        # ── 导出 ──
        st.divider()
        st.subheader("📤 导出")
        vid = inp.video_id or hashlib.md5(inp.text.encode("utf-8")).hexdigest()[:10]
        md = out.report
        js = out.to_json()
        c1, c2 = st.columns(2)
        c1.download_button("下载 .md 报告", md, file_name=f"albedo_{vid}.md", mime="text/markdown")
        c2.download_button("下载 .json 对象", js, file_name=f"albedo_{vid}.json",
                           mime="application/json")


if __name__ == "__main__":
    main()
