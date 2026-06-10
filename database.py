import sqlite3
from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_name TEXT NOT NULL,
            production_id TEXT NOT NULL,
            check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cheapest_price REAL,
            section TEXT,
            row TEXT,
            quantity INTEGER,
            deal_score REAL,
            total_listings INTEGER,
            total_tickets INTEGER,
            tickets_under_1000 INTEGER,
            tickets_under_750 INTEGER,
            tickets_under_500 INTEGER,
            section_breakdown TEXT
        )
        """
    )
    # Add columns if missing (existing databases)
    for col in ("total_tickets INTEGER", "tickets_under_1000 INTEGER", "tickets_under_750 INTEGER", "tickets_under_500 INTEGER", "section_breakdown TEXT"):
        try:
            conn.execute(f"ALTER TABLE price_checks ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS whatsapp_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            apikey TEXT NOT NULL,
            label TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_thresholds (
            production_id TEXT PRIMARY KEY,
            threshold_price REAL NOT NULL,
            last_alerted_at TIMESTAMP,
            last_alerted_price REAL
        )
        """
    )
    conn.commit()
    conn.close()


# --- Settings ---


def get_setting(key: str, default: str | None = None) -> str | None:
    """Get a setting value by key, returning default if not found."""
    conn = _connect()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    """Upsert a setting value."""
    conn = _connect()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


# --- WhatsApp contacts ---


def get_whatsapp_contacts() -> list[dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM whatsapp_contacts ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_whatsapp_contact(phone: str, apikey: str, label: str = ""):
    conn = _connect()
    conn.execute(
        "INSERT INTO whatsapp_contacts (phone, apikey, label) VALUES (?, ?, ?)",
        (phone, apikey, label),
    )
    conn.commit()
    conn.close()


def delete_whatsapp_contact(contact_id: int):
    conn = _connect()
    conn.execute("DELETE FROM whatsapp_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()


# --- Price thresholds ---


def get_price_thresholds() -> dict[str, dict]:
    """Return {production_id: {threshold_price, last_alerted_at, last_alerted_price}}."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM price_thresholds").fetchall()
    conn.close()
    return {r["production_id"]: dict(r) for r in rows}


def set_price_threshold(production_id: str, threshold_price: float):
    conn = _connect()
    conn.execute(
        "INSERT INTO price_thresholds (production_id, threshold_price) VALUES (?, ?) "
        "ON CONFLICT(production_id) DO UPDATE SET threshold_price = excluded.threshold_price",
        (production_id, threshold_price),
    )
    conn.commit()
    conn.close()


def delete_price_threshold(production_id: str):
    conn = _connect()
    conn.execute("DELETE FROM price_thresholds WHERE production_id = ?", (production_id,))
    conn.commit()
    conn.close()


def update_threshold_alert(production_id: str, alerted_price: float):
    """Record that an alert was sent for this match at this price."""
    conn = _connect()
    conn.execute(
        "UPDATE price_thresholds SET last_alerted_at = CURRENT_TIMESTAMP, "
        "last_alerted_price = ? WHERE production_id = ?",
        (alerted_price, production_id),
    )
    conn.commit()
    conn.close()


def save_price_check(data: dict):
    conn = _connect()
    conn.execute(
        """
        INSERT INTO price_checks
            (match_name, production_id, cheapest_price, section, row, quantity, deal_score, total_listings, total_tickets, tickets_under_1000, tickets_under_750, tickets_under_500, section_breakdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["match_name"],
            data["production_id"],
            data.get("cheapest_price"),
            data.get("section"),
            data.get("row"),
            data.get("quantity"),
            data.get("deal_score"),
            data.get("total_listings"),
            data.get("total_tickets"),
            data.get("tickets_under_1000"),
            data.get("tickets_under_750"),
            data.get("tickets_under_500"),
            data.get("section_breakdown"),
        ),
    )
    conn.commit()
    conn.close()


def get_latest_prices():
    """Return the most recent price check for each match."""
    conn = _connect()
    rows = conn.execute(
        """
        SELECT *
        FROM price_checks
        WHERE id IN (
            SELECT MAX(id) FROM price_checks GROUP BY production_id
        )
        ORDER BY match_name
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price_history(hours: int = 1):
    """Return all price checks within the last N hours, per match."""
    conn = _connect()
    rows = conn.execute(
        """
        SELECT *
        FROM price_checks
        WHERE check_time >= datetime('now', ?)
        ORDER BY match_name, check_time
        """,
        (f"-{hours} hours",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_chart_data(time_range: str = "24h") -> list[dict]:
    """Return price history for charts.

    time_range: "8h", "24h", "7d", or "all"
    """
    conn = _connect()
    if time_range == "all":
        rows = conn.execute(
            """
            SELECT production_id, match_name, check_time,
                   cheapest_price, total_tickets
            FROM price_checks
            WHERE cheapest_price IS NOT NULL
            ORDER BY production_id, check_time
            """
        ).fetchall()
    else:
        amount = int(time_range[:-1])
        unit = time_range[-1]
        offset = f"-{amount * 24} hours" if unit == "d" else f"-{amount} hours"
        rows = conn.execute(
            """
            SELECT production_id, match_name, check_time,
                   cheapest_price, total_tickets
            FROM price_checks
            WHERE cheapest_price IS NOT NULL
              AND check_time >= datetime('now', ?)
            ORDER BY production_id, check_time
            """,
            (offset,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_historical_low():
    """Return the all-time lowest price for each match."""
    conn = _connect()
    rows = conn.execute(
        """
        SELECT match_name, production_id, MIN(cheapest_price) AS low_price
        FROM price_checks
        WHERE cheapest_price IS NOT NULL
        GROUP BY production_id
        """
    ).fetchall()
    conn.close()
    return {r["production_id"]: dict(r) for r in rows}
