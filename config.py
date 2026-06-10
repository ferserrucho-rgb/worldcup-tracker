import os

MATCHES = [
    {
        "name": "Argentina vs Algeria (Match 19)",
        "production_id": "5080461",
        "url": "https://www.vividseats.com/fifa-world-cup/production/5080461",
        "date": "June 16, 2026 8:00 PM",
        "venue": "Arrowhead Stadium, Kansas City",
    },
    {
        "name": "Argentina vs Austria (Match 43)",
        "production_id": "5080516",
        "url": "https://www.vividseats.com/fifa-world-cup/production/5080516",
        "date": "June 22, 2026 8:00 PM",
        "venue": "AT&T Stadium, Arlington",
    },
    {
        "name": "Jordan vs Argentina (Match 70)",
        "production_id": "5080712",
        "url": "https://www.vividseats.com/fifa-world-cup/production/5080712",
        "date": "June 27, 2026 9:00 PM",
        "venue": "AT&T Stadium, Arlington",
    },
]

# Email configuration — all sensitive values from environment variables
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "ferserrucho@gmail.com")

# Scheduler intervals (minutes)
SCRAPE_INTERVAL_MINUTES = 15
EMAIL_INTERVAL_MINUTES = 30

# Web dashboard
WEB_PORT = 8080

# Database
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tickets.db")
