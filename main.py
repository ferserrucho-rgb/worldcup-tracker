import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from config import EMAIL_INTERVAL_MINUTES, SCRAPE_INTERVAL_MINUTES
from database import get_latest_prices, get_price_history, init_db, save_price_check
from notifier import send_price_report
from scraper import scrape_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def scrape_job():
    """Scrape all matches and save results to the database."""
    logger.info("Starting scheduled scrape ...")
    results = scrape_all()
    for data in results:
        save_price_check(data)
    logger.info("Scrape complete — %d matches processed.", len(results))


def email_job():
    """Send an hourly email summary."""
    logger.info("Preparing hourly email report ...")
    latest = get_latest_prices()
    history = get_price_history(hours=1)
    if not latest:
        logger.warning("No price data yet — skipping email.")
        return
    send_price_report(latest, history)


def main():
    logger.info("Initializing database ...")
    init_db()

    # Run first scrape immediately so there's data right away
    scrape_job()

    scheduler = BlockingScheduler()
    scheduler.add_job(scrape_job, "interval", minutes=SCRAPE_INTERVAL_MINUTES, id="scrape")
    scheduler.add_job(email_job, "interval", minutes=EMAIL_INTERVAL_MINUTES, id="email")

    def shutdown(signum, frame):
        logger.info("Shutting down ...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(
        "Scheduler started — scraping every %d min, emailing every %d min.",
        SCRAPE_INTERVAL_MINUTES,
        EMAIL_INTERVAL_MINUTES,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
