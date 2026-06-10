import logging
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import re

from config import GMAIL_APP_PASSWORD, GMAIL_USER, NOTIFY_EMAIL
from database import get_historical_low, get_setting, get_whatsapp_contacts


def _split_emails(emails: str) -> list[str]:
    """Split email string by comma, semicolon, or whitespace."""
    return [e.strip() for e in re.split(r"[,;\s]+", emails) if e.strip()]

logger = logging.getLogger(__name__)


def _build_html(price_data: list[dict], history_data: list[dict]) -> str:
    """Build an HTML email body with current prices, deltas, and historical lows."""
    historical_lows = get_historical_low()

    # Group history by production_id to compute hourly deltas
    history_by_match: dict[str, list[dict]] = {}
    for row in history_data:
        history_by_match.setdefault(row["production_id"], []).append(row)

    rows_html = ""
    for entry in price_data:
        pid = entry["production_id"]
        price = entry.get("cheapest_price")
        price_str = f"${price:,.2f}" if price is not None else "N/A"

        # Price change vs oldest entry in the last hour
        delta_html = ""
        if price is not None and pid in history_by_match:
            history = history_by_match[pid]
            old_prices = [h["cheapest_price"] for h in history if h["cheapest_price"] is not None]
            if old_prices:
                oldest = old_prices[0]
                delta = price - oldest
                if delta < 0:
                    delta_html = f'<span style="color:green;">&#9660; ${abs(delta):,.2f}</span>'
                elif delta > 0:
                    delta_html = f'<span style="color:red;">&#9650; ${delta:,.2f}</span>'
                else:
                    delta_html = '<span style="color:gray;">&#8212; $0</span>'

        # Historical low
        low = historical_lows.get(pid, {}).get("low_price")
        low_str = f"${low:,.2f}" if low is not None else "N/A"

        section = entry.get("section") or ""
        row_val = entry.get("row") or ""
        location = f"{section} / Row {row_val}" if section and row_val else section or row_val or "N/A"

        check_time = entry.get("check_time", "")

        rows_html += f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd;">{entry['match_name']}</td>
            <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">{price_str}</td>
            <td style="padding:8px;border:1px solid #ddd;">{delta_html}</td>
            <td style="padding:8px;border:1px solid #ddd;">{low_str}</td>
            <td style="padding:8px;border:1px solid #ddd;">{location}</td>
            <td style="padding:8px;border:1px solid #ddd;font-size:0.85em;">{check_time}</td>
        </tr>"""

    html = f"""\
    <html>
    <body style="font-family:Arial,sans-serif;">
        <h2>World Cup 2026 - Argentina Ticket Price Report</h2>
        <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <table style="border-collapse:collapse;width:100%;max-width:900px;">
            <tr style="background:#003087;color:white;">
                <th style="padding:8px;border:1px solid #ddd;">Match</th>
                <th style="padding:8px;border:1px solid #ddd;">Cheapest</th>
                <th style="padding:8px;border:1px solid #ddd;">1h Change</th>
                <th style="padding:8px;border:1px solid #ddd;">All-Time Low</th>
                <th style="padding:8px;border:1px solid #ddd;">Location</th>
                <th style="padding:8px;border:1px solid #ddd;">Last Check</th>
            </tr>
            {rows_html}
        </table>
        <p style="color:#888;font-size:0.85em;">Data sourced from Vivid Seats. Prices may change.</p>
    </body>
    </html>"""
    return html


def send_price_report(price_data: list[dict], history_data: list[dict]):
    """Send an HTML email report of current prices."""
    notify_emails = get_setting("notify_emails", NOTIFY_EMAIL)

    if not GMAIL_USER or not GMAIL_APP_PASSWORD or not notify_emails:
        logger.error(
            "Email not configured. Set GMAIL_USER, GMAIL_APP_PASSWORD, and NOTIFY_EMAIL env vars."
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"WC 2026 Argentina Tickets - {datetime.now().strftime('%b %d %H:%M')}"
    msg["From"] = GMAIL_USER
    msg["To"] = notify_emails

    html = _build_html(price_data, history_data)
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, _split_emails(notify_emails), msg.as_string())
        logger.info("Price report email sent to %s", notify_emails)
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)


# --- WhatsApp via CallMeBot ---


def send_whatsapp_message(phone: str, apikey: str, message: str):
    """Send a WhatsApp message via CallMeBot API."""
    encoded_msg = urllib.parse.quote(message)
    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={phone}&text={encoded_msg}&apikey={apikey}"
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
        logger.info("WhatsApp sent to %s (status %d)", phone, status)
    except Exception as exc:
        logger.error("WhatsApp send failed for %s: %s", phone, exc)


# --- Threshold alerts ---


def send_threshold_alert_whatsapp(alerts: list[dict], contacts: list[dict]):
    """Send WhatsApp messages for threshold alerts to all contacts."""
    for alert in alerts:
        msg = (
            f"PRICE ALERT: {alert['match_name']}\n"
            f"Price dropped to ${alert['price']:,.2f} "
            f"(threshold: ${alert['threshold']:,.2f})"
        )
        for contact in contacts:
            send_whatsapp_message(contact["phone"], contact["apikey"], msg)


def send_threshold_alert_email(alerts: list[dict], notify_emails: str):
    """Send an email for threshold price alerts."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        logger.error("Gmail credentials not configured, skipping threshold email.")
        return

    rows_html = ""
    for alert in alerts:
        rows_html += (
            f"<tr>"
            f"<td style='padding:8px;border:1px solid #ddd;'>{alert['match_name']}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;font-weight:bold;color:green;'>"
            f"${alert['price']:,.2f}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;'>${alert['threshold']:,.2f}</td>"
            f"</tr>"
        )

    html = f"""\
    <html><body style="font-family:Arial,sans-serif;">
    <h2 style="color:green;">Price Alert - Threshold Reached!</h2>
    <p>The following tickets have dropped below your price threshold:</p>
    <table style="border-collapse:collapse;">
        <tr style="background:#003087;color:white;">
            <th style="padding:8px;border:1px solid #ddd;">Match</th>
            <th style="padding:8px;border:1px solid #ddd;">Current Price</th>
            <th style="padding:8px;border:1px solid #ddd;">Your Threshold</th>
        </tr>
        {rows_html}
    </table>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "PRICE ALERT - WC 2026 Tickets Below Threshold!"
    msg["From"] = GMAIL_USER
    msg["To"] = notify_emails

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, _split_emails(notify_emails), msg.as_string())
        logger.info("Threshold alert email sent to %s", notify_emails)
    except Exception as exc:
        logger.error("Failed to send threshold email: %s", exc)
