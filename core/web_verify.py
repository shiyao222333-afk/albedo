"""Albedo (Lian Zhen) · Layer3 联网核查框架 (v0.4.2, 规模期进路线图，本轮落框架)

对 Layer2(MiniCheck 本地) 仍 unverified 的「可证伪公开事实主张」做联网检索升级判定。
可插拔检索后端(backend)：默认无 ALBEDO_SEARCH_API_KEY → 诚实降级标 web_status="pending"
（待联网核查），不臆断为真、不静默放过。配置 key + 后端后自动启用真联网。

设计原则（与 Layer2 一致）：保守。未核实不过高；降级明说"待联网核查"。
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger("albedo.web_verify")

# 检索后端凭证：用户配了才真联网；否则诚实降级
SEARCH_API_KEY = os.environ.get("ALBEDO_SEARCH_API_KEY", "")


def web_verify_claims(claims: list, *, backend=None) -> tuple:
    """对候选主张做联网升级核查。

    候选 = check_worthy + scope=public + factuality=factual + accuracy=unverified。
    无 key/后端 → 全部标 web_status="pending"（诚实降级），不改 accuracy。
    有后端 → 调 backend(claim) 返回 {"accuracy","evidence","confidence"} 升级判定。

    返回 (updated_count, pending_count)。
    """
    claims = claims or []
    has_backend = bool(SEARCH_API_KEY) or backend is not None

    updated = 0
    pending = 0
    for c in claims:
        candidate = (
            c.get("check_worthy")
            and c.get("scope") == "public"
            and c.get("factuality") == "factual"
            and c.get("accuracy") == "unverified"
        )
        if not candidate:
            continue
        if not has_backend:
            c["web_status"] = "pending"
            pending += 1
            continue
        try:
            res = backend(c) if backend else None
        except Exception as e:
            logger.warning("web_verify backend 异常，降级 pending：%s", e)
            res = None
        if res:
            c["accuracy"] = res.get("accuracy", c.get("accuracy"))
            c["evidence"] = res.get("evidence", "")
            c["confidence"] = res.get("confidence", c.get("confidence", 0.0))
            c["web_status"] = "verified"
            updated += 1
        else:
            c["web_status"] = "pending"
            pending += 1
    return updated, pending
