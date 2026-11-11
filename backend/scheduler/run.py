"""Dedicated scheduler service (run instead of / alongside the API with SCHEDULER_ENABLED=false on the API).

    python -m backend.scheduler.run            # keeps running, checks sources at the configured PKT hours
    python -m backend.scheduler.run --once     # run one check now and exit (useful for Windows Task Scheduler)
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import threading

from backend.database.db import init_db
from backend.scheduler.scheduler import run_scheduled_check, scheduler_info, start_scheduler, stop_scheduler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--force", action="store_true", help="ignore per-provider politeness windows")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    if args.once:
        print(json.dumps(run_scheduled_check(trigger="cli", force=args.force), indent=2, default=str))
        return
    if not start_scheduler():
        print("Scheduler not started (disabled, or already running in another process).")
        return
    print(json.dumps(scheduler_info(), indent=2))
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    stop_scheduler()


if __name__ == "__main__":
    main()
