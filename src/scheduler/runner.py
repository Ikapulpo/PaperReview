"""Weekly scheduler for automated paper review (NKT + Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)

_SCHEDULER_MAP = {
    "monday": lambda: schedule.every().monday,
    "tuesday": lambda: schedule.every().tuesday,
    "wednesday": lambda: schedule.every().wednesday,
    "thursday": lambda: schedule.every().thursday,
    "friday": lambda: schedule.every().friday,
    "saturday": lambda: schedule.every().saturday,
    "sunday": lambda: schedule.every().sunday,
}


def _get_day_scheduler(day: str):
    day = day.lower()
    if day not in _SCHEDULER_MAP:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"
    return _SCHEDULER_MAP[day]()


def run_weekly_review():
    """Execute one cycle of the NKT weekly review pipeline."""
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"NKT pipeline execution failed: {e}", exc_info=True)


def run_spine_weekly_review():
    """Execute one cycle of the spine weekly review pipeline."""
    from src.spine.pipeline import execute_spine_pipeline
    try:
        execute_spine_pipeline()
    except Exception as e:
        logger.error(f"Spine pipeline execution failed: {e}", exc_info=True)


def start_scheduler():
    """Start the NKT weekly scheduler."""
    day = config.schedule_day
    time_str = config.schedule_time
    _get_day_scheduler(day).at(time_str).do(run_weekly_review)

    logger.info(f"NKT scheduler started: runs every {day} at {time_str}")
    print(f"✓ NKTスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_spine_scheduler():
    """Start the Spine weekly scheduler."""
    day = config.spine_schedule_day
    time_str = config.spine_schedule_time
    _get_day_scheduler(day).at(time_str).do(run_spine_weekly_review)

    logger.info(f"Spine scheduler started: runs every {day} at {time_str}")
    print(f"✓ Spineスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)
