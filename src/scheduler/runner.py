"""Weekly scheduler for automated paper review (NKT + Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)

SCHEDULER_MAP = {
    "monday": schedule.every().monday,
    "tuesday": schedule.every().tuesday,
    "wednesday": schedule.every().wednesday,
    "thursday": schedule.every().thursday,
    "friday": schedule.every().friday,
    "saturday": schedule.every().saturday,
    "sunday": schedule.every().sunday,
}


def run_weekly_review():
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"NKT pipeline execution failed: {e}", exc_info=True)


def run_spine_review():
    from src.spine.pipeline import execute_spine_pipeline
    try:
        execute_spine_pipeline()
    except Exception as e:
        logger.error(f"Spine pipeline execution failed: {e}", exc_info=True)


def _run_loop():
    while True:
        schedule.run_pending()
        time.sleep(60)


def start_scheduler():
    day = config.schedule_day.lower()
    time_str = config.schedule_time

    if day not in SCHEDULER_MAP:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"

    SCHEDULER_MAP[day].at(time_str).do(run_weekly_review)

    logger.info(f"NKT scheduler started: runs every {day} at {time_str}")
    print(f"✓ NKTスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    _run_loop()


def start_spine_scheduler():
    day = config.spine_schedule_day.lower()
    time_str = config.spine_schedule_time

    if day not in SCHEDULER_MAP:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"

    SCHEDULER_MAP[day].at(time_str).do(run_spine_review)

    logger.info(f"Spine scheduler started: runs every {day} at {time_str}")
    print(f"✓ スパインスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    _run_loop()
