import json
import logging
from collections import defaultdict
from datetime import datetime

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from config import MATCHES

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

LISTINGS_API = "https://www.vividseats.com/hermes/api/v1/listings?productionId={}"

_VIP_KEYWORDS = ("VIP", "CHAMPION", "TROPHY", "PAVILION", "PITCHSIDE", "LOUNGE", "LUXURY", "SUITE", "CLUB")


def _classify_section(section: str) -> str:
    """Classify a section name into a category."""
    sec = section.upper().strip()

    # VIP / Premium
    if any(kw in sec for kw in _VIP_KEYWORDS):
        return "VIP/Premium"

    # Named categories: "CATEGORY 1", "CATEGORY 2", etc.
    if "CATEGORY 1" in sec or "CAT1" in sec:
        return "Category 1"
    if "CATEGORY 2" in sec or "CAT2" in sec:
        return "Category 2"
    if "CATEGORY 3" in sec or "CAT3" in sec:
        return "Category 3"
    if "CATEGORY 4" in sec or "CAT4" in sec:
        return "Category 4"

    # Numeric sections: extract the leading number
    import re
    m = re.search(r"(\d{3})", sec)
    if m:
        num = int(m.group(1))
        if 100 <= num <= 199:
            return "100 Level"
        if 200 <= num <= 299:
            return "200 Level"
        if 300 <= num <= 399:
            return "300 Level"
        if 400 <= num <= 499:
            return "400 Level"

    return "Other"


def _fetch_via_api(session, production_id):
    """Fetch ticket listings from the Vivid Seats listings API."""
    url = LISTINGS_API.format(production_id)
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Listings API failed for %s: %s", production_id, exc)
        return None

    tickets = data.get("tickets", [])
    if not tickets:
        return None

    # Find the cheapest listing — tickets have short keys:
    # s=section, r=row, q=quantity, p=price, d=deal score
    cheapest = min(tickets, key=lambda t: float(t.get("p", 999999)))

    global_info = data.get("global", [{}])[0]

    total_tickets = sum(int(t.get("q", 0)) for t in tickets)
    tickets_under_1000 = sum(int(t.get("q", 0)) for t in tickets if float(t.get("p", 999999)) < 1000)
    tickets_under_750 = sum(int(t.get("q", 0)) for t in tickets if float(t.get("p", 999999)) < 750)
    tickets_under_500 = sum(int(t.get("q", 0)) for t in tickets if float(t.get("p", 999999)) < 500)

    # Group tickets by section category
    section_groups = defaultdict(int)
    for t in tickets:
        qty = int(t.get("q", 0))
        sec = str(t.get("s", "")).strip().upper()
        section_groups[_classify_section(sec)] += qty

    return {
        "cheapest_price": float(cheapest["p"]),
        "section": cheapest.get("s", ""),
        "row": cheapest.get("r", ""),
        "quantity": int(cheapest.get("q", 0)),
        "deal_score": None,
        "total_listings": int(global_info.get("listingCount", 0)),
        "total_tickets": total_tickets,
        "tickets_under_1000": tickets_under_1000,
        "tickets_under_750": tickets_under_750,
        "tickets_under_500": tickets_under_500,
        "section_breakdown": json.dumps(dict(section_groups)),
    }


def _fetch_via_page(session, url):
    """Fallback: fetch the production page and extract data from __NEXT_DATA__."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Page fetch failed: %s", exc)
        return None

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag or not script_tag.string:
        return None

    try:
        data = json.loads(script_tag.string)
    except json.JSONDecodeError:
        return None

    props = data.get("props", {}).get("pageProps", {})
    prod = props.get("initialProductionDetailsData", {}).get("data", {})

    cheapest_price = prod.get("minAipPrice") or prod.get("minPrice")
    if cheapest_price is None:
        return None

    return {
        "cheapest_price": float(cheapest_price),
        "section": "",
        "row": "",
        "quantity": 0,
        "deal_score": None,
        "total_listings": prod.get("listingCount"),
    }


def scrape_match(match):
    """Scrape a single match and return structured price data."""
    result = {
        "match_name": match["name"],
        "production_id": match["production_id"],
        "cheapest_price": None,
        "section": None,
        "row": None,
        "quantity": None,
        "deal_score": None,
        "total_listings": None,
    }

    session = cffi_requests.Session(impersonate="chrome")

    # Visit the page first to establish cookies
    try:
        session.get(match["url"], timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except Exception:
        pass

    # Primary: listings API (has per-listing quantity)
    extracted = _fetch_via_api(session, match["production_id"])

    # Fallback: parse __NEXT_DATA__ from the page
    if extracted is None:
        logger.info("Falling back to page parsing for %s", match["name"])
        extracted = _fetch_via_page(session, match["url"])

    if extracted:
        result.update(extracted)
    else:
        logger.warning("Could not extract price data for %s", match["name"])

    # Compute days until match
    try:
        match_dt = datetime.strptime(match["date"], "%B %d, %Y %I:%M %p")
        delta = match_dt - datetime.now()
        result["days_until"] = max(0, delta.days)
    except ValueError:
        result["days_until"] = None

    return result


def scrape_all():
    """Scrape all configured matches and return list of results."""
    results = []
    for match in MATCHES:
        logger.info("Scraping %s ...", match["name"])
        data = scrape_match(match)
        if data["cheapest_price"] is not None:
            logger.info(
                "  -> $%.2f | %d available | %d listings",
                data["cheapest_price"],
                data.get("quantity") or 0,
                data.get("total_listings") or 0,
            )
        else:
            logger.warning("  -> no price found")
        results.append(data)
    return results
