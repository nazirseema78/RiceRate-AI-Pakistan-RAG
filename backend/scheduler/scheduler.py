"""APScheduler-based source checks at 09:00, 12:00, 15:00 and 18:00 Pakistan Standard Time.

Duplicate execution is prevented with an OS-level file lock: when several backend workers start,
only the one that acquires `storage/scheduler.lock` starts the scheduler. Each job run also takes a
second lock so a manual refresh and a scheduled run never overlap.

A scheduled check does NOT guarantee a newly published price: if a source has not published
anything new, the previous observation is kept with its original timestamp.
"""
from __future__ import annotations

import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from filelock import FileLock, Timeout

from backend.config import get_settings

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
_leader_lock: FileLock | None = None


def job_lock() -> FileLock:
    p = Path(get_settings().scheduler_lock_path).with_suffix(".job.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(p))


def run_scheduled_check(trigger: str = "scheduled", force: bool = False) -> list[dict]:
    from backend.services.market_data.ingestion import run_all

    try:
        with job_lock().acquire(timeout=0):
            results = run_all(trigger=trigger, force=force)
            log.info("Source check (%s) finished: %s", trigger,
                     ", ".join(f"{r['provider']}={r['status']}(+{r.get('inserted', 0)})" for r in results))
            return results
    except Timeout:
        log.warning("Another ingestion run is in progress - skipped")
        return [{"provider": "*", "status": "skipped", "message": "another ingestion run is in progress"}]


def start_scheduler() -> bool:
    """Start the scheduler if this process wins the leader lock. Returns True if started here."""
    global _scheduler, _leader_lock
    s = get_settings()
    if not s.scheduler_enabled or _scheduler is not None:
        return False
    Path(s.scheduler_lock_path).parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(s.scheduler_lock_path))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        log.info("Scheduler already running in another process - not starting a second one")
        return False
    _leader_lock = lock
    _scheduler = BackgroundScheduler(timezone=s.timezone)
    _scheduler.add_job(run_scheduled_check, CronTrigger(hour=s.scheduler_hours, minute=0, timezone=s.timezone),
                       id="source_check", max_instances=1, coalesce=True, misfire_grace_time=1800, replace_existing=True)
    _scheduler.start()
    log.info("Scheduler started: hours %s (%s)", s.scheduler_hours, s.timezone)
    return True


def stop_scheduler() -> None:
    global _scheduler, _leader_lock
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    if _leader_lock:
        _leader_lock.release()
        _leader_lock = None


def scheduler_info() -> dict:
    s = get_settings()
    job = _scheduler.get_job("source_check") if _scheduler else None
    return {"enabled": s.scheduler_enabled, "running_in_this_process": _scheduler is not None,
            "hours_pkt": s.scheduler_hours, "timezone": s.timezone,
            "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None}
