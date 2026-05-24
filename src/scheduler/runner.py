"""Weekly scheduler for automated paper review (NKT + Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)


def run_weekly_nkt_review():
    """Execute one cycle of the NKT weekly review pipeline."""
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"NKT pipeline execution failed: {e}", exc_info=True)


def run_weekly_spine_review():
    """Execute one cycle of the spine weekly review pipeline."""
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
    return scheduler_map.get(day)


def start_scheduler():
    """Start the weekly scheduler for both NKT and Spine pipelines."""
    # NKT schedule
    nkt_day = config.schedule_day.lower()
    nkt_time = config.schedule_time
    nkt_sched = _get_scheduler_for_day(nkt_day)
    if not nkt_sched:
        logger.error(f"Invalid NKT schedule day: {nkt_day}. Using monday.")
        nkt_day = "monday"
        nkt_sched = _get_scheduler_for_day("monday")
    nkt_sched.at(nkt_time).do(run_weekly_nkt_review)
    print(f"✓ 週刊NKTスケジューラ: 毎週{nkt_day} {nkt_time}")

    # Spine schedule
    spine_day = config.spine_schedule_day.lower()
    spine_time = config.spine_schedule_time
    spine_sched = _get_scheduler_for_day(spine_day)
    if not spine_sched:
        logger.error(f"Invalid Spine schedule day: {spine_day}. Using monday.")
        spine_day = "monday"
        spine_sched = _get_scheduler_for_day("monday")
    spine_sched.at(spine_time).do(run_weekly_spine_review)
    print(f"✓ 週刊スパインスケジューラ: 毎週{spine_day} {spine_time}")

    logger.info(
        f"Scheduler started: NKT={nkt_day} {nkt_time}, Spine={spine_day} {spine_time}"
    )
    print("  Ctrl+C で停止")

    while True:
        schedule.run_pending()
        time.sleep(60)
