"""
⚗️ Albedo 全局配置（文件夹契约层，2026-07-12）

炼真作为前端管线中段，靠「监控目录 + 输出目录」与上下游解耦：
  - WATCH_DIR : 监控 馏析(Nigredo) 的中转①输出（默认 = 馏析 OUTPUT_DIR）
  - OUTPUT_DIR: 写出 中转②（默认 = 熔知 Citrinitas 活跃收件箱 library/inbox）
两目录各器独立、env 可配（落实用户「三个项目都要可设定」）。

人审闸门 REQUIRE_HUMAN_REVIEW：
  - false（默认，调试优先）：中转②直接写进 OUTPUT_DIR，被熔知监控摄入
  - true：中转②先写 OUTPUT_DIR/review_pending/，需晋级才进入熔知
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent

# === 中转①监控目录（上游 = 馏析 OUTPUT_DIR）===
WATCH_DIR = Path(os.getenv("ALBEDO_WATCH_DIR", r"D:\opus-magnum\front_half\transit\nigredo_out"))

# === 中转②输出目录（下游 = 熔知活跃收件箱）===
OUTPUT_DIR = Path(os.getenv("ALBEDO_OUTPUT_DIR", r"D:\citrinitas\library\inbox"))

# === 人审闸门 ===
REQUIRE_HUMAN_REVIEW = os.getenv("ALBEDO_REQUIRE_HUMAN_REVIEW", "false").lower() == "true"

# === 轮询间隔（秒）===
POLL_INTERVAL = float(os.getenv("ALBEDO_POLL_INTERVAL", "5"))

# === 验收开关：保留中转①（KEEP_INPUT）===
# 统一「巨作验收流程」开关 ACCEPTANCE_KEEP_FILES：harness 拉起炼真 / 熔知时通过此变量=1 开启，
# 两器同时受控（炼真保留中转①、熔知保留收件箱原文件）。改一个开关即可，验收结束停服务即恢复。
# 开启后，_archive 不把中转①移入 done/，而是改名 .keep 留在 WATCH_DIR：
#   - 不被删除（防误删）
#   - watcher 只扫 *.md，.keep 不会被重处理
# 平时不带该变量 → 原归档行为（移入 done/），不影响正常链路。
KEEP_INPUT = os.getenv("ACCEPTANCE_KEEP_FILES", "false").lower() in ("1", "true", "yes")

# 确保目录存在（独立进程也能自建）
WATCH_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
