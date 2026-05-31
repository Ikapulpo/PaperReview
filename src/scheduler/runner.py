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
    """Execute one cycle of the NKT weekly review pipeline."""
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"NKT pipeline execution failed: {e}", exc_info=True)


def run_spine_review():
    """Execute one cycle of the Spine weekly review pipeline."""
    from src.spine.pipeline import execute_spine_pipeline
    try:
        execute_spine_pipeline()
    except Exception as e:
        logger.error(f"Spine pipeline execution failed: {e}", exc_info=True)


def _resolve_day(day_str: str, fallback: str = "monday") -> str:
    day = day_str.lower()
    if day not in SCHEDULER_MAP:
        logger.error(f"Invalid schedule day: {day}. Using {fallback}.")
        day = fallback
    return day


def start_scheduler():
    """Start the NKT-only weekly scheduler."""
    day = _resolve_day(config.schedule_day)
    time_str = config.schedule_time

    SCHEDULER_MAP[day].at(time_str).do(run_weekly_review)

    logger.info(f"NKT scheduler started: runs every {day} at {time_str}")
    print(f"✓ NKTスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_spine_scheduler():
    """Start the Spine-only weekly scheduler."""
    day = _resolve_day(config.spine_schedule_day)
    time_str = config.spine_schedule_time

    SCHEDULER_MAP[day].at(time_str).do(run_spine_review)

    logger.info(f"Spine scheduler started: runs every {day} at {time_str}")
    print(f"✓ Spineスケジューラ起動: 毎週{day} {time_str} に実行")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)


def start_all_schedulers():
    """Start both NKT and Spine weekly schedulers."""
    nkt_day = _resolve_day(config.schedule_day)
    nkt_time = config.schedule_time
    spine_day = _resolve_day(config.spine_schedule_day)
    spine_time = config.spine_schedule_time

    SCHEDULER_MAP[nkt_day].at(nkt_time).do(run_weekly_review)
    SCHEDULER_MAP[spine_day].at(spine_time).do(run_spine_review)

    logger.info(f"All schedulers started: NKT={nkt_day} {nkt_time}, Spine={spine_day} {spine_time}")
    print(f"✓ 統合スケジューラ起動:")
    print(f"  NKT:   毎週{nkt_day} {nkt_time}")
    print(f"  Spine: 毎週{spine_day} {spine_time}")
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)
