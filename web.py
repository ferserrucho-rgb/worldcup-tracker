import json
import logging
import os
from datetime import datetime

from flask import Flask, redirect, request, url_for

from config import (
    MATCHES,
    NOTIFY_EMAIL,
    SCRAPE_INTERVAL_MINUTES,
    WEB_PORT,
)
from database import (
    add_whatsapp_contact,
    delete_price_threshold,
    delete_whatsapp_contact,
    get_chart_data,
    get_historical_low,
    get_latest_prices,
    get_price_history,
    get_price_thresholds,
    get_setting,
    get_whatsapp_contacts,
    set_price_threshold,
    set_setting,
)

logger = logging.getLogger(__name__)

app = Flask(__name__)

COMMON_CSS = """\
    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
    h1 { color: #003087; }
    h2 { color: #003087; margin-top: 30px; }
    a { color: #003087; }
    table.dashboard { border-collapse: collapse; width: 100%; background: white; margin-bottom: 15px; table-layout: fixed; }
    table.dashboard th { background: #003087; color: white; padding: 8px 5px; border: 1px solid #ddd; text-align: center; font-size: 0.8em; }
    table.dashboard td { padding: 6px 5px; border: 1px solid #ddd; text-align: center; font-size: 0.85em; }
    table.dashboard td:first-child, table.dashboard th:first-child { text-align: left; }
    table.dashboard td.breakdown { text-align: left; font-size: 0.78em; line-height: 1.45; padding: 6px 8px; }
    table.dashboard .cat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px 12px; }
    table.dashboard .cat-item { white-space: nowrap; }
    table { border-collapse: collapse; width: 100%; max-width: 1600px; background: white; margin-bottom: 15px; }
    th { background: #003087; color: white; padding: 10px; border: 1px solid #ddd; text-align: left; }
    td { padding: 10px; border: 1px solid #ddd; }
    tr:nth-child(even) { background: #f9f9f9; }
    .timestamp { color: #888; font-size: 0.85em; margin-top: 12px; }
    .nav { margin-bottom: 20px; font-size: 0.95em; }
    .nav a { margin-right: 15px; text-decoration: none; font-weight: bold; }
    .nav a:hover { text-decoration: underline; }
    .success { background: #d4edda; color: #155724; padding: 10px 15px; border-radius: 4px; margin-bottom: 15px; max-width: 1600px; }
    .form-section { background: white; padding: 20px; border-radius: 6px; border: 1px solid #ddd; max-width: 1600px; margin-bottom: 20px; }
    label { display: block; font-weight: bold; margin-bottom: 4px; margin-top: 12px; }
    input[type="number"], input[type="text"], input[type="email"], textarea {
        padding: 8px; border: 1px solid #ccc; border-radius: 4px; width: 100%; max-width: 400px; box-sizing: border-box;
    }
    textarea { height: 60px; resize: vertical; }
    button, .btn {
        background: #003087; color: white; border: none; padding: 10px 20px;
        border-radius: 4px; cursor: pointer; font-size: 0.95em; margin-top: 12px;
    }
    button:hover, .btn:hover { background: #004db3; }
    .btn-danger { background: #dc3545; }
    .btn-danger:hover { background: #c82333; }
    .btn-sm { padding: 5px 12px; font-size: 0.85em; margin-top: 0; }
    .inline-form { display: inline; }
    .chart-controls { margin: 10px 0 15px 0; }
    .range-btn {
        background: #e0e0e0; color: #333; border: 1px solid #ccc;
        padding: 6px 16px; margin-right: 5px; border-radius: 4px;
        cursor: pointer; font-size: 0.9em;
    }
    .range-btn:hover { background: #d0d0d0; }
    .range-btn.active { background: #003087; color: white; border-color: #003087; }
    .chart-wrapper {
        background: white; border: 1px solid #ddd; border-radius: 6px;
        padding: 15px; margin-bottom: 15px; max-width: 1600px;
    }
    .chart-wrapper h3 { margin: 0 0 10px 0; color: #003087; font-size: 1em; }
"""


def _days_until(date_str: str) -> int | None:
    """Compute days remaining until a match date string."""
    try:
        match_dt = datetime.strptime(date_str, "%B %d, %Y %I:%M %p")
        delta = match_dt - datetime.now()
        return max(0, delta.days)
    except ValueError:
        return None


# --- Dashboard ---


@app.route("/")
def dashboard():
    latest = get_latest_prices()
    history = get_price_history(hours=1)
    historical_lows = get_historical_low()

    match_lookup = {m["production_id"]: m for m in MATCHES}

    history_by_match: dict[str, list[dict]] = {}
    for row in history:
        history_by_match.setdefault(row["production_id"], []).append(row)

    # Chart data
    chart_rows = get_chart_data(time_range="all")
    chart_by_match: dict[str, dict] = {}
    for row in chart_rows:
        pid = row["production_id"]
        if pid not in chart_by_match:
            chart_by_match[pid] = {
                "match_name": row["match_name"],
                "timestamps": [],
                "prices": [],
                "tickets": [],
            }
        chart_by_match[pid]["timestamps"].append(row["check_time"])
        chart_by_match[pid]["prices"].append(row["cheapest_price"])
        chart_by_match[pid]["tickets"].append(row["total_tickets"])
    chart_json = json.dumps(chart_by_match)

    rows_html = ""
    for entry in latest:
        pid = entry["production_id"]
        price = entry.get("cheapest_price")
        price_str = f"${price:,.2f}" if price is not None else "N/A"
        qty = entry.get("quantity") or 0

        delta_html = ""
        if price is not None and pid in history_by_match:
            old_prices = [
                h["cheapest_price"]
                for h in history_by_match[pid]
                if h["cheapest_price"] is not None
            ]
            if old_prices:
                oldest = old_prices[0]
                delta = price - oldest
                if delta < 0:
                    delta_html = f'<span style="color:green;">&#9660; ${abs(delta):,.2f}</span>'
                elif delta > 0:
                    delta_html = f'<span style="color:red;">&#9650; ${delta:,.2f}</span>'
                else:
                    delta_html = '<span style="color:gray;">&#8212; $0</span>'

        low = historical_lows.get(pid, {}).get("low_price")
        low_str = f"${low:,.2f}" if low is not None else "N/A"

        section = entry.get("section") or "N/A"
        total_listings = entry.get("total_listings") or 0
        total_tickets = entry.get("total_tickets") or 0
        tickets_under_1000 = entry.get("tickets_under_1000") or 0
        tickets_under_750 = entry.get("tickets_under_750") or 0
        tickets_under_500 = entry.get("tickets_under_500") or 0

        # Section breakdown
        raw_breakdown = entry.get("section_breakdown") or "{}"
        try:
            breakdown = json.loads(raw_breakdown)
        except (json.JSONDecodeError, TypeError):
            breakdown = {}
        category_order = ["VIP/Premium", "Category 1", "100 Level", "Category 2", "200 Level", "Category 3", "300 Level", "Category 4", "400 Level", "Other"]
        breakdown_parts = []
        for cat in category_order:
            if cat in breakdown and breakdown[cat] > 0:
                breakdown_parts.append(f'<span class="cat-item"><b>{cat}:</b> {breakdown[cat]}</span>')
        breakdown_html = f'<div class="cat-grid">{"".join(breakdown_parts)}</div>' if breakdown_parts else "N/A"

        match_cfg = match_lookup.get(pid)
        days = _days_until(match_cfg["date"]) if match_cfg else None
        days_str = str(days) if days is not None else "N/A"

        rows_html += f"""
            <tr>
                <td>{entry['match_name']}</td>
                <td style="font-weight:bold;">{price_str}</td>
                <td>{qty}</td>
                <td>{delta_html}</td>
                <td>{low_str}</td>
                <td>{section}</td>
                <td>{days_str}</td>
                <td>{total_listings}</td>
                <td>{total_tickets}</td>
                <td>{tickets_under_1000}</td>
                <td>{tickets_under_750}</td>
                <td>{tickets_under_500}</td>
                <td class="breakdown">{breakdown_html}</td>
            </tr>"""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    charts_html = ""
    for match in MATCHES:
        pid = match["production_id"]
        charts_html += f"""
        <div class="chart-wrapper">
            <h3>{match['name']}</h3>
            <canvas id="chart-{pid}"></canvas>
        </div>"""

    html = f"""\
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="60">
    <title>WC 2026 Argentina Ticket Tracker</title>
    <style>{COMMON_CSS}</style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
</head>
<body>
    <div class="nav">
        <a href="/">Dashboard</a>
        <a href="/settings">Settings</a>
    </div>
    <h1>World Cup 2026 &mdash; Argentina Ticket Tracker</h1>
    <table class="dashboard" style="width:100%;">
        <colgroup>
            <col style="width:14%;">
            <col style="width:6%;">
            <col style="width:3%;">
            <col style="width:7%;">
            <col style="width:6%;">
            <col style="width:5%;">
            <col style="width:4%;">
            <col style="width:5%;">
            <col style="width:5%;">
            <col style="width:5%;">
            <col style="width:5%;">
            <col style="width:5%;">
            <col style="width:30%;">
        </colgroup>
        <tr>
            <th>Match</th>
            <th>Cheapest</th>
            <th>Qty</th>
            <th>1h Change</th>
            <th>All-Time Low</th>
            <th>Section</th>
            <th>Days</th>
            <th>Listings</th>
            <th>Tickets</th>
            <th>&lt;$1,000</th>
            <th>&lt;$750</th>
            <th>&lt;$500</th>
            <th style="text-align:left;">By Category</th>
        </tr>
        {rows_html}
    </table>
    <p class="timestamp">Last updated: {now} &bull; Auto-refreshes every 60 seconds</p>

    <h2>Price History</h2>
    <div class="chart-controls">
        <button class="range-btn" data-range="8h">8h</button>
        <button class="range-btn" data-range="24h">24h</button>
        <button class="range-btn" data-range="7d">7d</button>
        <button class="range-btn active" data-range="all">All</button>
    </div>
    {charts_html}

    <script>
    const chartData = {chart_json};
    const chartInstances = {{}};
    const MATCH_COLORS = {{
        '5080461': {{price: '#003087', tickets: '#82b1ff'}},
        '5080516': {{price: '#2e7d32', tickets: '#81c784'}},
        '5080712': {{price: '#c62828', tickets: '#ef9a9a'}}
    }};

    function filterByRange(timestamps, data, range) {{
        if (range === 'all') return {{timestamps, data}};
        const now = new Date();
        let ms;
        if (range === '8h') ms = 8 * 3600000;
        else if (range === '24h') ms = 24 * 3600000;
        else if (range === '7d') ms = 7 * 86400000;
        else ms = 0;
        const cutoff = new Date(now.getTime() - ms);
        const ft = [], fd = [];
        for (let i = 0; i < timestamps.length; i++) {{
            if (new Date(timestamps[i]) >= cutoff) {{
                ft.push(timestamps[i]);
                fd.push(data[i]);
            }}
        }}
        return {{timestamps: ft, data: fd}};
    }}

    function renderCharts(range) {{
        Object.keys(chartData).forEach(pid => {{
            const match = chartData[pid];
            const colors = MATCH_COLORS[pid] || {{price: '#003087', tickets: '#82b1ff'}};
            const pf = filterByRange(match.timestamps, match.prices, range);
            const tf = filterByRange(match.timestamps, match.tickets, range);

            if (chartInstances[pid]) chartInstances[pid].destroy();

            const ctx = document.getElementById('chart-' + pid);
            if (!ctx) return;

            const datasets = [{{
                label: 'Cheapest Price ($)',
                data: pf.data,
                borderColor: colors.price,
                backgroundColor: colors.price + '20',
                borderWidth: 2,
                pointRadius: 2,
                tension: 0.3,
                fill: true,
                yAxisID: 'y'
            }}];

            const scales = {{
                x: {{
                    type: 'time',
                    time: {{
                        tooltipFormat: 'MMM d, HH:mm',
                        displayFormats: {{ minute: 'HH:mm', hour: 'MMM d, HH:mm' }}
                    }}
                }},
                y: {{
                    type: 'linear',
                    position: 'left',
                    title: {{ display: true, text: 'Price ($)' }},
                    ticks: {{ callback: v => '$' + v.toLocaleString() }}
                }}
            }};

            // Only add tickets axis if data exists
            const hasTickets = tf.data.some(v => v != null);
            if (hasTickets) {{
                datasets.push({{
                    label: 'Total Tickets',
                    data: tf.data,
                    borderColor: colors.tickets,
                    borderWidth: 1.5,
                    borderDash: [5, 3],
                    pointRadius: 0,
                    tension: 0.3,
                    fill: false,
                    yAxisID: 'y1'
                }});
                scales.y1 = {{
                    type: 'linear',
                    position: 'right',
                    title: {{ display: true, text: 'Tickets' }},
                    grid: {{ drawOnChartArea: false }}
                }};
            }}

            chartInstances[pid] = new Chart(ctx, {{
                type: 'line',
                data: {{ labels: pf.timestamps, datasets }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    aspectRatio: 3,
                    interaction: {{ mode: 'index', intersect: false }},
                    scales,
                    plugins: {{
                        tooltip: {{
                            callbacks: {{
                                label: function(ctx) {{
                                    if (ctx.dataset.yAxisID === 'y')
                                        return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString();
                                    return ctx.dataset.label + ': ' + (ctx.parsed.y != null ? ctx.parsed.y.toLocaleString() : 'N/A');
                                }}
                            }}
                        }}
                    }}
                }}
            }});
        }});
    }}

    renderCharts('all');

    document.querySelectorAll('.range-btn').forEach(btn => {{
        btn.addEventListener('click', function() {{
            document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            renderCharts(this.dataset.range);
        }});
    }});
    </script>
</body>
</html>"""
    return html


# --- Settings page ---


@app.route("/settings")
def settings_page():
    notify_emails = get_setting("notify_emails", NOTIFY_EMAIL)
    scrape_interval = get_setting("scrape_interval", str(SCRAPE_INTERVAL_MINUTES))
    thresholds = get_price_thresholds()
    contacts = get_whatsapp_contacts()
    latest = get_latest_prices()

    # Map production_id -> latest price for display
    price_lookup = {e["production_id"]: e.get("cheapest_price") for e in latest}

    saved_banner = ""
    if request.args.get("saved"):
        saved_banner = '<div class="success">Settings saved successfully.</div>'

    # --- General settings section ---
    general_html = f"""
    <div class="form-section">
        <h2>General</h2>
        <form method="POST" action="/settings">
            <label for="notify_emails">Email recipients (comma-separated)</label>
            <textarea id="notify_emails" name="notify_emails">{notify_emails or ""}</textarea>

            <label for="scrape_interval">Scrape interval (minutes)</label>
            <input type="number" id="scrape_interval" name="scrape_interval"
                   value="{scrape_interval}" min="1" max="1440">
            <p style="color:#555;font-size:0.85em;margin-top:4px;">
                Email notifications are sent automatically when price changes are detected.
            </p>
    """

    # --- Thresholds section (inside same form) ---
    threshold_rows = ""
    for match in MATCHES:
        pid = match["production_id"]
        current_price = price_lookup.get(pid)
        price_str = f"${current_price:,.2f}" if current_price is not None else "N/A"
        threshold_val = thresholds.get(pid, {}).get("threshold_price")
        threshold_input = f'{threshold_val:.0f}' if threshold_val is not None else ""
        last_alert = thresholds.get(pid, {}).get("last_alerted_at") or "Never"

        threshold_rows += f"""
            <tr>
                <td>{match['name']}</td>
                <td>{price_str}</td>
                <td><input type="number" name="threshold_{pid}" value="{threshold_input}"
                           placeholder="e.g. 500" step="1" min="0"
                           style="width:120px;"></td>
                <td style="font-size:0.85em;color:#888;">{last_alert}</td>
            </tr>"""

    threshold_html = f"""
        <h2>Price Threshold Alerts</h2>
        <p style="color:#555;font-size:0.9em;">
            Set a price threshold per match. When the cheapest ticket drops below this price,
            you will receive an email and WhatsApp alert.
            Leave empty to disable alerts for that match.
        </p>
        <table>
            <tr>
                <th>Match</th>
                <th>Current Price</th>
                <th>Alert Below ($)</th>
                <th>Last Alert</th>
            </tr>
            {threshold_rows}
        </table>
        <button type="submit">Save Settings</button>
        </form>
    </div>
    """

    # --- WhatsApp contacts section ---
    contact_rows = ""
    for c in contacts:
        contact_rows += f"""
            <tr>
                <td>{c['phone']}</td>
                <td>{c['apikey']}</td>
                <td>{c.get('label') or ''}</td>
                <td>
                    <form class="inline-form" method="POST" action="/settings/whatsapp/delete">
                        <input type="hidden" name="contact_id" value="{c['id']}">
                        <button type="submit" class="btn-danger btn-sm">Delete</button>
                    </form>
                </td>
            </tr>"""

    if not contacts:
        contact_rows = '<tr><td colspan="4" style="color:#888;">No contacts configured.</td></tr>'

    whatsapp_html = f"""
    <div class="form-section">
        <h2>WhatsApp Contacts (CallMeBot)</h2>
        <p style="color:#555;font-size:0.9em;">
            Each recipient must first register with CallMeBot by sending
            <code>I allow callmebot to send me messages</code> to
            <strong>+34 644 71 82 04</strong> on WhatsApp, then enter their phone and API key below.
        </p>
        <table>
            <tr>
                <th>Phone</th>
                <th>API Key</th>
                <th>Label</th>
                <th></th>
            </tr>
            {contact_rows}
        </table>

        <h3 style="margin-top:15px;">Add Contact</h3>
        <form method="POST" action="/settings/whatsapp/add" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;">
            <div>
                <label for="wa_phone" style="margin-top:0;">Phone</label>
                <input type="text" id="wa_phone" name="phone" placeholder="+5491123456789" style="width:180px;" required>
            </div>
            <div>
                <label for="wa_apikey" style="margin-top:0;">API Key</label>
                <input type="text" id="wa_apikey" name="apikey" placeholder="123456" style="width:120px;" required>
            </div>
            <div>
                <label for="wa_label" style="margin-top:0;">Label</label>
                <input type="text" id="wa_label" name="label" placeholder="Federico" style="width:150px;">
            </div>
            <div>
                <button type="submit" style="margin-top:0;">Add</button>
            </div>
        </form>
    </div>
    """

    html = f"""\
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Settings - WC 2026 Tracker</title>
    <style>{COMMON_CSS}</style>
</head>
<body>
    <div class="nav">
        <a href="/">Dashboard</a>
        <a href="/settings">Settings</a>
    </div>
    <h1>Settings</h1>
    {saved_banner}
    {general_html}
    {threshold_html}
    {whatsapp_html}
</body>
</html>"""
    return html


@app.route("/settings", methods=["POST"])
def settings_save():
    # Save general settings
    notify_emails = request.form.get("notify_emails", "").strip()
    scrape_interval = request.form.get("scrape_interval", "").strip()

    if notify_emails:
        set_setting("notify_emails", notify_emails)

    # Validate and save scrape interval
    try:
        scrape_mins = max(1, int(scrape_interval))
    except (ValueError, TypeError):
        scrape_mins = SCRAPE_INTERVAL_MINUTES
    set_setting("scrape_interval", str(scrape_mins))

    # Save price thresholds
    for match in MATCHES:
        pid = match["production_id"]
        val = request.form.get(f"threshold_{pid}", "").strip()
        if val:
            try:
                set_price_threshold(pid, float(val))
            except ValueError:
                pass
        else:
            delete_price_threshold(pid)

    # Reschedule scrape job if scheduler is available
    scheduler = app.config.get("scheduler")
    if scheduler:
        try:
            scheduler.reschedule_job("scrape", trigger="interval", minutes=scrape_mins)
            logger.info("Rescheduled scrape job — every %d min.", scrape_mins)
        except Exception as exc:
            logger.error("Failed to reschedule jobs: %s", exc)

    return redirect(url_for("settings_page", saved=1))


@app.route("/settings/whatsapp/add", methods=["POST"])
def whatsapp_add():
    phone = request.form.get("phone", "").strip()
    apikey = request.form.get("apikey", "").strip()
    label = request.form.get("label", "").strip()
    if phone and apikey:
        add_whatsapp_contact(phone, apikey, label)
    return redirect(url_for("settings_page"))


@app.route("/settings/whatsapp/delete", methods=["POST"])
def whatsapp_delete():
    contact_id = request.form.get("contact_id")
    if contact_id:
        delete_whatsapp_contact(int(contact_id))
    return redirect(url_for("settings_page"))


def start_web():
    """Start the Flask web server (meant to be called from a background thread)."""
    port = int(os.environ.get("PORT", WEB_PORT))
    logger.info("Starting web dashboard on 0.0.0.0:%d", port)
    app.run(host="0.0.0.0", port=port, use_reloader=False)
