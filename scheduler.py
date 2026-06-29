import yaml
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from agent import run_agent
from deliver import deliver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def daily_run():
    logging.info("Daily run starting...")
    try:
        briefing = run_agent()
        deliver(briefing)
        logging.info("Daily run complete.")
    except Exception as e:
        logging.error(f"Daily run failed: {e}")
        deliver(f"⚠️ Research agent error: {e}")

def main():
    with open("goal_profile.yaml") as f:
        profile = yaml.safe_load(f)

    delivery_time = profile.get("delivery_time", "10:30")
    timezone = profile.get("timezone", "Asia/Taipei")
    hour, minute = map(int, delivery_time.split(":"))

    scheduler = BlockingScheduler(timezone=timezone)
    job = scheduler.add_job(
        daily_run,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily_briefing"
    )

    # job.next_run_time isn't populated until the scheduler actually starts
    # in this APScheduler version, so compute it from the trigger directly.
    next_run = job.trigger.get_next_fire_time(None, datetime.now(scheduler.timezone))
    logging.info(f"Scheduler started. Next run: {next_run}")
    logging.info(f"Delivery time: {delivery_time} {timezone}")
    logging.info("Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logging.info("Scheduler stopped.")

if __name__ == "__main__":
    main()
