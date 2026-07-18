"""中转②产出：refine() → 写 {bv}_refined.md（含文件头 YAML frontmatter 机读契约）。
机读契约权威文档：albedo-citrinitas-handoff-spec.md（Claw 工作区根目录）；本模块只按契约产出，不定义契约。

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

    # 目标目录（人审闸门）
    target_dir = OUTPUT_DIR
    if REQUIRE_HUMAN_REVIEW:
        target_dir = OUTPUT_DIR / "review_pending"
    target_dir.mkdir(parents=True, exist_ok=True)

    md_path = target_dir / f"{bv_id}_refined.md"

    # v1.1 B-only：frontmatter（机读契约）已由 render_report 经 build_ingestion_frontmatter
    # 注入报告头部，不再单独写 sidecar .meta.json（用户决策③：frontmatter 升唯一主载体）。
    md_path.write_text(out.report, encoding="utf-8")

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
    }
