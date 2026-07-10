"""Albedo (Lian Zhen) · 来源溯源 (A3 / C6)

build_provenance(inp) 从上游（馏析）传入的 AlbedoInput 抽取来源元数据，
生成精炼对象的 provenance 字段。

设计要点（v0.2.0 锁定决策，见 PROJECT_PLAN.md §四 A3）：
  - 纯函数，**不调用任何 LLM**；仅读取已归一化传入的元数据。
  - processed_at 统一用 **ISO 8601 UTC**（如 2026-07-09T16:05:00Z）。
  - 缺字段一律**留空字符串**，绝不因缺字段而抛异常中断流水线。
  - 溯源种类的进一步扩展（平台归一化 / 适配器版本 / 采集时间 / 引用锚点等）
    列入研究课题（PROJECT_PLAN.md §6.1「★ 溯源种类扩展研究」，v0.4.0 起归本模块）。

对外暴露：
  - build_provenance(inp, *, now=None) -> dict
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from core.models import AlbedoInput


# ISO 8601 UTC 格式（带 Z 后缀，无时区偏移段），与 PROJECT_PLAN 锁定示例一致
_ISO_UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _iso_utc_now() -> str:
    """当前 UTC 时间，格式 2026-07-09T16:05:00Z。"""
    return datetime.now(timezone.utc).strftime(_ISO_UTC_FMT)


def _blank_if_missing(value) -> str:
    """把 None / 仅空白 归一为空白字符串，其余原值仅去首尾空白。"""
    if value is None:
        return ""
    return str(value).strip()


def build_provenance(
    inp: Optional[AlbedoInput],
    *,
    now: Optional[datetime] = None,
) -> dict:
    """从上游输入抽取来源元数据，返回 provenance dict。

    参数:
      inp: 对齐 Nigredo 的生料对象（video_id / up_name / source_url / title）；
           也接受等价的普通 dict；传 None 视为全缺字段。
      now: 可选注入当前时间（测试 / 可复现用）；不传用真实 UTC 当前时间。

    返回:
      {
        "video_id":    str,  # 可能为空（非视频来源，如社媒文案）
        "up_name":     str,  # 可能为空
        "source_url":  str,  # 可能为空
        "title":       str,  # 可能为空
        "processed_at": str,  # ISO 8601 UTC，必填
      }

    健壮性：inp 为 None / 缺属性 / 字段空白时对应值留空，processed_at 始终填充；
    任何单字段缺失都只留空，不抛异常。
    """
    # 时间基准：统一换算成 UTC 再格式化（naive 视为 UTC，aware 转 UTC）
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    processed_at = now.strftime(_ISO_UTC_FMT)

    if inp is None:
        return {
            "video_id": "",
            "up_name": "",
            "source_url": "",
            "title": "",
            "processed_at": processed_at,
        }

    # 同时兼容 AlbedoInput 对象与普通 dict（上游 JSON 反序列化场景）
    if isinstance(inp, dict):
        get = inp.get
    else:
        get = lambda k, default="": getattr(inp, k, default)

    return {
        "video_id": _blank_if_missing(get("video_id")),
        "up_name": _blank_if_missing(get("up_name")),
        "source_url": _blank_if_missing(get("source_url")),
        "title": _blank_if_missing(get("title")),
        "processed_at": processed_at,
    }
