"""Weekly scheduler for automated paper review."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)


def run_weekly_review():
    """Execute one cycle of the weekly review pipeline."""
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)


def start_scheduler():
    """Start the weekly scheduler.

    Runs the review pipeline on the configured day and time.
    Default: every Monday at 09:00.
    """
    day = config.schedule_day.lower()
    time_str = config.schedule_time

    scheduler_map = {
        "monday": schedule.every().monday,
        "tuesday": schedule.every().tuesday,
        "wednesday": schedule.every().wednesday,
        "thursday": schedule.every().thursday,
        "friday": schedule.every().friday,
        "saturday": schedule.every().saturday,
        "sunday": schedule.every().sunday,
    }

    if day not in scheduler_map:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"

    scheduler_map[day].at(time_str).do(run_weekly_review)

    logger.info(f"Scheduler started: runs every {day} at {time_str}")
    print(f"✓ スケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)
