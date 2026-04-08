"""Weekly scheduler for automated paper review (NKT and Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)


# ── NKT ─────────────────────────────────────────────────────────────────

def run_weekly_review():
    """Execute one cycle of the NKT weekly review pipeline."""
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"NKT pipeline execution failed: {e}", exc_info=True)


def start_scheduler():
    """Start the NKT weekly scheduler.

    Runs the review pipeline on the configured day and time.
    Default: every Monday at 09:00.
    """
    day = config.schedule_day.lower()
    time_str = config.schedule_time

    scheduler_map = _build_scheduler_map()

    if day not in scheduler_map:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"

    scheduler_map[day].at(time_str).do(run_weekly_review)

    logger.info(f"NKT scheduler started: runs every {day} at {time_str}")
    print(f"✓ NKTスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


# ── Spine ───────────────────────────────────────────────────────────────

def run_spine_weekly_review():
    """Execute one cycle of the spine weekly review pipeline."""
    from src.spine_pipeline import execute_spine_pipeline
    try:
        execute_spine_pipeline()
    except Exception as e:
        logger.error(f"Spine pipeline execution failed: {e}", exc_info=True)


def start_spine_scheduler():
    """Start the spine weekly scheduler.

    Runs the spine review pipeline on the configured day and time.
    Default: every Monday at 08:00.
    """
    day = config.spine_schedule_day.lower()
    time_str = config.spine_schedule_time

    scheduler_map = _build_scheduler_map()

    if day not in scheduler_map:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"

    scheduler_map[day].at(time_str).do(run_spine_weekly_review)

    logger.info(f"Spine scheduler started: runs every {day} at {time_str}")
    print(f"✓ Spineスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


# ── Helpers ─────────────────────────────────────────────────────────────

def _build_scheduler_map():
    return {
        "monday": schedule.every().monday,
        "tuesday": schedule.every().tuesday,
        "wednesday": schedule.every().wednesday,
        "thursday": schedule.every().thursday,
        "friday": schedule.every().friday,
        "saturday": schedule.every().saturday,
        "sunday": schedule.every().sunday,
    }
