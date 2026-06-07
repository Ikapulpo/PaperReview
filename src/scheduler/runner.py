"""Weekly scheduler for automated paper review (NKT + Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)

SCHEDULER_MAP = {
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


def _register_job(day_str: str, time_str: str, job_fn, label: str):
    day = day_str.lower()
    if day not in SCHEDULER_MAP:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"
    SCHEDULER_MAP[day]().at(time_str).do(job_fn)
    logger.info(f"{label} scheduled: every {day} at {time_str}")
    print(f"  ✓ {label}: 毎週{day} {time_str}")


def start_scheduler():
    """Start the combined weekly scheduler for NKT and Spine.

    NKT:   configured via SCHEDULE_DAY / SCHEDULE_TIME
    Spine: configured via SPINE_SCHEDULE_DAY / SPINE_SCHEDULE_TIME
    """
    print("スケジューラ起動中...")

    _register_job(
        config.schedule_day, config.schedule_time,
        run_weekly_review, "週刊NKT",
    )
    _register_job(
        config.spine_schedule_day, config.spine_schedule_time,
        run_spine_weekly_review, "週刊スパイン",
    )

    print("  Ctrl+C で停止\n")

    while True:
        schedule.run_pending()
        time.sleep(60)
