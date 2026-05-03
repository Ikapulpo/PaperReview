"""Weekly scheduler for automated paper review (NKT + Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)

_SCHEDULER_MAP_FACTORY = {
    "monday": lambda: schedule.every().monday,
    "tuesday": lambda: schedule.every().tuesday,
    "wednesday": lambda: schedule.every().wednesday,
    "thursday": lambda: schedule.every().thursday,
    "friday": lambda: schedule.every().friday,
    "saturday": lambda: schedule.every().saturday,
    "sunday": lambda: schedule.every().sunday,
}


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


def _schedule_job(day: str, time_str: str, job_func, label: str):
    day = day.lower()
    if day not in _SCHEDULER_MAP_FACTORY:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"
    _SCHEDULER_MAP_FACTORY[day]().at(time_str).do(job_func)
    logger.info(f"{label} scheduler: every {day} at {time_str}")
    print(f"✓ {label}スケジューラ起動: 毎週{day} {time_str} に実行")


def start_scheduler():
    """Start the NKT weekly scheduler."""
    _schedule_job(
        config.schedule_day, config.schedule_time,
        run_weekly_review, "週刊NKT",
    )
    print("  Ctrl+C で停止")
    while True:
        schedule.run_pending()
        time.sleep(60)


def start_spine_scheduler():
    """Start the spine weekly scheduler."""
    _schedule_job(
        config.spine_schedule_day, config.spine_schedule_time,
        run_spine_weekly_review, "週刊スパイン",
    )
    print("  Ctrl+C で停止")
    while True:
        schedule.run_pending()
        time.sleep(60)


def start_all_schedulers():
    """Start both NKT and spine schedulers together."""
    _schedule_job(
        config.schedule_day, config.schedule_time,
        run_weekly_review, "週刊NKT",
    )
    _schedule_job(
        config.spine_schedule_day, config.spine_schedule_time,
        run_spine_weekly_review, "週刊スパイン",
    )
    print("  Ctrl+C で停止")
    while True:
        schedule.run_pending()
        time.sleep(60)
