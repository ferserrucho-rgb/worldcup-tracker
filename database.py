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
            total_listings INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


def save_price_check(data: dict):
    conn = _connect()
    conn.execute(
        """
        INSERT INTO price_checks
            (match_name, production_id, cheapest_price, section, row, quantity, deal_score, total_listings)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
