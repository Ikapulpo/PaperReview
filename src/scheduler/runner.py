"""Weekly scheduler for automated paper review (NKT + Spine)."""

import logging
import time

import schedule

from src.config import config

logger = logging.getLogger(__name__)


def _run_nkt():
    from src.pipeline import execute_pipeline
    try:
        execute_pipeline()
    except Exception as e:
        logger.error(f"NKT pipeline failed: {e}", exc_info=True)


def _run_spine():
    from src.spine.pipeline import execute_spine_pipeline
    try:
        execute_spine_pipeline()
    except Exception as e:
        logger.error(f"Spine pipeline failed: {e}", exc_info=True)


def _schedule_job(day: str, time_str: str, job_func, label: str):
    scheduler_map = {
        "monday": schedule.every().monday,
        "tuesday": schedule.every().tuesday,
        "wednesday": schedule.every().wednesday,
        "thursday": schedule.every().thursday,
        "friday": schedule.every().friday,
        "saturday": schedule.every().saturday,
        "sunday": schedule.every().sunday,
    }
    day = day.lower()
    if day not in scheduler_map:
        logger.error(f"Invalid schedule day: {day}. Using monday.")
        day = "monday"

    scheduler_map[day].at(time_str).do(job_func)
    logger.info(f"{label} scheduler: every {day} at {time_str}")
    print(f"  ✓ {label}: 毎週{day} {time_str}")


def _run_loop():
    print("  Ctrl+C で停止")
    while True:
        schedule.run_pending()
        time.sleep(60)


def start_nkt_scheduler():
    print("✓ NKTスケジューラ起動:")
    _schedule_job(config.schedule_day, config.schedule_time, _run_nkt, "週刊NKT")
    _run_loop()


def start_spine_scheduler():
    print("✓ 脊椎スケジューラ起動:")
    _schedule_job(config.spine_schedule_day, config.spine_schedule_time, _run_spine, "週刊スパイン")
    _run_loop()


def start_all_schedulers():
    print("✓ 統合スケジューラ起動:")
    _schedule_job(config.schedule_day, config.schedule_time, _run_nkt, "週刊NKT")
    _schedule_job(config.spine_schedule_day, config.spine_schedule_time, _run_spine, "週刊スパイン")
    _run_loop()


# Backward compatibility
start_scheduler = start_nkt_scheduler
