"""Weekly scheduler for automated paper review."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)


def run_weekly_review():
    """Execute one cycle of the weekly NKT review pipeline."""
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"NKT pipeline execution failed: {e}", exc_info=True)


def run_spine_review():
    """Execute one cycle of the weekly spine review pipeline."""
    from src.spine.pipeline import execute_spine_pipeline
    try:
        execute_spine_pipeline()
    except Exception as e:
        logger.error(f"Spine pipeline execution failed: {e}", exc_info=True)


def _get_scheduler_for_day(day: str):
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
        return schedule.every().monday
    return scheduler_map[day]


def start_scheduler():
    """Start the weekly scheduler for NKT.

    Runs the review pipeline on the configured day and time.
    Default: every Monday at 09:00.
    """
    day = config.schedule_day.lower()
    time_str = config.schedule_time

    _get_scheduler_for_day(day).at(time_str).do(run_weekly_review)

    logger.info(f"NKT Scheduler started: runs every {day} at {time_str}")
    print(f"✓ NKTスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_spine_scheduler():
    """Start the weekly scheduler for Spine.

    Default: every Monday at 08:00.
    """
    day = config.spine_schedule_day.lower()
    time_str = config.spine_schedule_time

    _get_scheduler_for_day(day).at(time_str).do(run_spine_review)

    logger.info(f"Spine Scheduler started: runs every {day} at {time_str}")
    print(f"✓ スパインスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_all_schedulers():
    """Start both NKT and Spine schedulers."""
    nkt_day = config.schedule_day.lower()
    nkt_time = config.schedule_time
    spine_day = config.spine_schedule_day.lower()
    spine_time = config.spine_schedule_time

    _get_scheduler_for_day(nkt_day).at(nkt_time).do(run_weekly_review)
    _get_scheduler_for_day(spine_day).at(spine_time).do(run_spine_review)

    logger.info("All schedulers started")
    print(f"✓ NKTスケジューラ: 毎週{nkt_day} {nkt_time}")
    print(f"✓ スパインスケジューラ: 毎週{spine_day} {spine_time}")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)
