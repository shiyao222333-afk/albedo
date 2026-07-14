"""Albedo 中转监控包（文件夹契约中段，2026-07-12）

- parser : 中转① {bv}.md → AlbedoInput
- processor : refine() → 写中转② {bv}_refined.md + .meta.json + 归档
- run : 常驻轮询进程（PID 锁 / 重启强杀 / 优雅退出）
"""
from __future__ import annotations

from watcher import parser, processor, run

__all__ = ["parser", "processor", "run"]
