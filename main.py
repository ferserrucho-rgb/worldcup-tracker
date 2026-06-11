import logging
import os
import signal
import sys
import threading

from config import NOTIFY_EMAIL, SCRAPE_INTERVAL_MINUTES
from database import (
    get_latest_prices,
    get_price_history,
    get_price_thresholds,
    get_setting,
    get_whatsapp_contacts,
    init_db,
    save_price_check,
    update_threshold_alert,
)
from notifier import (
    send_price_report,
    send_threshold_alert_email,
    send_threshold_alert_whatsapp,
)
from scraper import scrape_all
from web import app, start_web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def check_threshold_alerts():
    """Check if any match price dropped below its threshold and send alerts."""
    thresholds = get_price_thresholds()
    if not thresholds:
        return

    latest = get_latest_prices()
    alerts_to_send = []

    for entry in latest:
        pid = entry["production_id"]
        price = entry.get("cheapest_price")
        if price is None or pid not in thresholds:
            continue

        threshold_info = thresholds[pid]
        threshold_price = threshold_info["threshold_price"]

        if price > threshold_price:
            continue

        # Only alert if never alerted before or price dropped further
        last_alerted_price = threshold_info.get("last_alerted_price")
        if last_alerted_price is not None and price >= last_alerted_price:
            continue

        alerts_to_send.append({
            "match_name": entry["match_name"],
            "production_id": pid,
            "price": price,
            "threshold": threshold_price,
        })

    if not alerts_to_send:
        return

    logger.info("Threshold alerts triggered for %d match(es).", len(alerts_to_send))

    # Send email alert
    notify_emails = get_setting("notify_emails", NOTIFY_EMAIL)
    if notify_emails:
        send_threshold_alert_email(alerts_to_send, notify_emails)

    # Send WhatsApp alerts
    contacts = get_whatsapp_contacts()
    if contacts:
        send_threshold_alert_whatsapp(alerts_to_send, contacts)

    # Mark alerts as sent
    for alert in alerts_to_send:
        update_threshold_alert(alert["production_id"], alert["price"])


def scrape_job():
    """Scrape all matches, save results, and notify if prices changed."""
    logger.info("Starting scheduled scrape ...")

    # Snapshot current prices before scraping
    previous = {e["production_id"]: e.get("cheapest_price") for e in get_latest_prices()}

    results = scrape_all()
    for data in results:
        save_price_check(data)
    logger.info("Scrape complete — %d matches processed.", len(results))

    # Check if any price changed
    changed = False
    for data in results:
        pid = data["production_id"]
        new_price = data.get("cheapest_price")
        old_price = previous.get(pid)
        if new_price != old_price:
            changed = True
            direction = ""
            if old_price is not None and new_price is not None:
                diff = new_price - old_price
                direction = f" ({'+'if diff > 0 else ''}{diff:,.2f})"
            logger.info(
                "Price change detected: %s — $%s -> $%s%s",
                data["match_name"],
                f"{old_price:,.2f}" if old_price is not None else "N/A",
                f"{new_price:,.2f}" if new_price is not None else "N/A",
                direction,
            )

    if changed:
        logger.info("Prices changed — sending email report.")
        latest = get_latest_prices()
        history = get_price_history(hours=1)
        send_price_report(latest, history)
    else:
        logger.info("No price changes detected — skipping email.")

    check_threshold_alerts()


def main():
    logger.info("Initializing database ...")
    init_db()

    # On Render (or any platform without a scheduler), just run the web server.
    # Scraping happens on-demand via web.py's before_request hook.
    if os.environ.get("RENDER"):
        logger.info("Running on Render — web-only mode (on-demand scraping).")
        scrape_job()  # initial scrape
        start_web()
        return

    # Local mode: run scheduler + web server in background thread
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    app.config["scheduler"] = scheduler

    web_thread = threading.Thread(target=start_web, daemon=True)
    web_thread.start()

    scrape_job()

    scrape_mins = int(get_setting("scrape_interval", str(SCRAPE_INTERVAL_MINUTES)))
    scheduler.add_job(scrape_job, "interval", minutes=scrape_mins, id="scrape")

    def shutdown(signum, frame):
        logger.info("Shutting down ...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(
        "Scheduler started — scraping every %d min, email on price change only.",
        scrape_mins,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
