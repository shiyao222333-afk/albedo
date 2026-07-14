"""中转②产出：refine() → 写 {bv}_refined.md + {bv}_refined.meta.json

- REQUIRE_HUMAN_REVIEW=false：写进 OUTPUT_DIR（被熔知监控摄入）
- REQUIRE_HUMAN_REVIEW=true：写进 OUTPUT_DIR/review_pending/（待晋级）
- 处理成功后源文件移入 WATCH_DIR/done/；失败移入 WATCH_DIR/failed/
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from config import WATCH_DIR, OUTPUT_DIR, REQUIRE_HUMAN_REVIEW
from flows.refine import refine
from watcher.parser import parse_transit_md

logger = logging.getLogger(__name__)


_EPISTEMIC_MAP = {
    "true": "corroborated",
    "suspect": "unverified",
    "false": "rejected",
}


def _derive_ingestion_meta(out) -> None:
    """ADR-005 最小预填：epistemic_status + trust_score（v0.1.0 两稳字段）。"""
    try:
        label = out.quality.truthfulness.label
        out.ingestion_meta.epistemic_status = _EPISTEMIC_MAP.get(label, "unverified")
    except Exception:
        out.ingestion_meta.epistemic_status = "unverified"
    try:
        out.ingestion_meta.trust_score = float(out.trust_score or 0.0)
    except Exception:
        out.ingestion_meta.trust_score = 0.0


def _archive(src_path: Path, ok: bool) -> None:
    dest_dir = WATCH_DIR / ("done" if ok else "failed")
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src_path), str(dest_dir / src_path.name))
    except Exception as e:
        logger.warning(f"归档失败 {src_path}: {e}")


def process_file(src_path: str | Path) -> dict:
    """处理一个中转①文件，返回结果摘要。异常上抛由 run 层捕获。"""
    src_path = Path(src_path)
    bv_id = src_path.stem  # {bv}.md → bv

    inp = parse_transit_md(src_path)
    out = refine(inp)

    _derive_ingestion_meta(out)

    # 目标目录（人审闸门）
    target_dir = OUTPUT_DIR
    if REQUIRE_HUMAN_REVIEW:
        target_dir = OUTPUT_DIR / "review_pending"
    target_dir.mkdir(parents=True, exist_ok=True)

    md_path = target_dir / f"{bv_id}_refined.md"
    meta_path = target_dir / f"{bv_id}_refined.meta.json"

    md_path.write_text(out.report, encoding="utf-8")
    meta_path.write_text(out.to_json(), encoding="utf-8")

    logger.info(
        f"中转②已落盘: {md_path} (status={out.status}, "
        f"人审={'开' if REQUIRE_HUMAN_REVIEW else '关'})"
    )

    # 源文件归档，避免重处理
    _archive(src_path, ok=True)

    return {
        "bv_id": bv_id,
        "status": out.status,
        "md": str(md_path),
        "meta": str(meta_path),
    }
