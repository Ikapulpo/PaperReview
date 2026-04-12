"""Weekly scheduler for automated paper review (NKT + Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)


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


def _get_scheduler_func(day: str):
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
    return scheduler_map[day]


def start_scheduler():
    """Start the NKT weekly scheduler."""
    day = config.schedule_day.lower()
    time_str = config.schedule_time

    _get_scheduler_func(day).at(time_str).do(run_weekly_review)

    logger.info(f"NKT scheduler started: runs every {day} at {time_str}")
    print(f"✓ NKTスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_spine_scheduler():
    """Start the spine weekly scheduler."""
    day = config.spine_schedule_day.lower()
    time_str = config.spine_schedule_time

    _get_scheduler_func(day).at(time_str).do(run_spine_weekly_review)

    logger.info(f"Spine scheduler started: runs every {day} at {time_str}")
    print(f"✓ Spineスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_all_schedulers():
    """Start both NKT and spine schedulers in a single process."""
    nkt_day = config.schedule_day.lower()
    nkt_time = config.schedule_time
    spine_day = config.spine_schedule_day.lower()
    spine_time = config.spine_schedule_time

    _get_scheduler_func(nkt_day).at(nkt_time).do(run_weekly_review)
    _get_scheduler_func(spine_day).at(spine_time).do(run_spine_weekly_review)

    logger.info(f"All schedulers started: NKT={nkt_day} {nkt_time}, Spine={spine_day} {spine_time}")
    print(f"✓ 全スケジューラ起動:")
    print(f"  NKT:   毎週{nkt_day} {nkt_time}")
    print(f"  Spine: 毎週{spine_day} {spine_time}")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)
