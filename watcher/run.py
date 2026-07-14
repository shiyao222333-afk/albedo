"""Albedo 中转监控常驻进程（文件夹契约中段，2026-07-12）

- 启动：读取 .watcher.pid，若旧实例存活则强杀（重启强制关，参考熔知 port_cleanup）
- 轮询 WATCH_DIR 顶级 *.md（跳过 review_pending/done/failed 子目录）
- 每个文件交给 processor.process_file；成功归档 done/，失败归档 failed/
- 优雅退出：捕获 SIGINT/SIGTERM，清理 pid 文件

运行：python -m watcher.run  （由 run.bat 在 UI 之外以独立进程拉起）
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

# 确保项目根在 sys.path（独立进程运行 -m watcher.run 时也能 import config/core/flows）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import WATCH_DIR, POLL_INTERVAL
from watcher import processor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [albedo-watcher] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

PID_FILE = PROJECT_ROOT / ".watcher.pid"

_stop = False


def _handle_signal(signum, frame):
    global _stop
    logger.info(f"收到退出信号 {signum}，准备停止…")
    _stop = True


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _claim_lock() -> None:
    """强杀旧实例并写入自身 PID（重启强制关）。"""
    old = _read_pid()
    if old and old != os.getpid() and _is_alive(old):
        logger.info(f"发现旧实例 PID={old}，强制关闭…")
        try:
            os.kill(old, signal.SIGTERM)
        except Exception:
            pass
        time.sleep(1)
        if _is_alive(old):
            try:
                os.kill(old, signal.SIGKILL)
            except Exception:
                pass
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        logger.warning(f"写 PID 文件失败：{e}")


def _release_lock() -> None:
    try:
        if _read_pid() == os.getpid():
            PID_FILE.unlink()
    except Exception:
        pass


def scan_once() -> int:
    """扫描并处理一轮顶级 *.md，返回处理数量。"""
    count = 0
    for md in sorted(WATCH_DIR.glob("*.md")):
        if not md.is_file():
            continue
        count += 1
        try:
            processor.process_file(md)
        except Exception as e:
            logger.exception(f"处理失败 {md.name}: {e}")
            processor._archive(md, ok=False)
    return count


def main() -> None:
    _claim_lock()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    logger.info(f"炼真监控启动：监控 {WATCH_DIR}（每 {POLL_INTERVAL}s 轮询）")
    try:
        while not _stop:
            try:
                n = scan_once()
                if n:
                    logger.info(f"本轮回处理的文件：{n}")
            except Exception as e:
                logger.warning(f"扫描异常：{e}")
            # 分段休眠，保证退出信号响应及时（~0.1s 粒度）
            steps = max(1, int(POLL_INTERVAL * 10))
            for _ in range(steps):
                if _stop:
                    break
                time.sleep(0.1)
    finally:
        _release_lock()
        logger.info("炼真监控已停止。")


if __name__ == "__main__":
    main()
