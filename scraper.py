import json
import logging

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from config import MATCHES

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


def _extract_from_next_data(html):
    """Extract ticket data from the __NEXT_DATA__ JSON embedded in the page."""
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag or not script_tag.string:
        return None

    try:
        data = json.loads(script_tag.string)
    except json.JSONDecodeError:
        logger.warning("Failed to parse __NEXT_DATA__ JSON")
        return None

    props = data.get("props", {}).get("pageProps", {})

    prod = props.get("initialProductionDetailsData", {}).get("data", {})
    deals = props.get("initialTopDealListingsData", {}).get("data", {})

    # Use all-in price (minAipPrice) as the "real" cheapest price a buyer pays.
    # Fall back to base minPrice if all-in isn't available.
    cheapest_price = prod.get("minAipPrice") or prod.get("minPrice")
    if cheapest_price is None:
        return None

    cheapest_price = float(cheapest_price)

    # Best section/row info from the top deals list
    section = ""
    row = ""
    deal_score = None
    top_deals = deals.get("topDeals", [])
    if top_deals:
        best = top_deals[0]
        section = best.get("section", "")
        row = best.get("row", "")
        deal_score = best.get("score")

    return {
        "cheapest_price": cheapest_price,
        "section": section,
        "row": row,
        "quantity": prod.get("ticketCount"),
        "deal_score": float(deal_score) if deal_score is not None else None,
        "total_listings": prod.get("listingCount"),
    }


def _parse_html_fallback(html):
    """Fallback: extract price from JSON-LD or visible HTML elements."""
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue
        offers = ld.get("offers") if isinstance(ld, dict) else None
        if offers:
            low = offers.get("lowPrice") or offers.get("price")
            if low:
                return {
                    "cheapest_price": float(low),
                    "section": "",
                    "row": "",
                    "quantity": None,
                    "deal_score": None,
                    "total_listings": None,
                }

    return None


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

    try:
        resp = cffi_requests.get(
            match["url"],
            impersonate="chrome",
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.error("HTTP error for %s: %s", match["name"], exc)
        return result

    html = resp.text

    extracted = _extract_from_next_data(html)

    if extracted is None:
        logger.info("Falling back to HTML parsing for %s", match["name"])
        extracted = _parse_html_fallback(html)

    if extracted:
        result.update(extracted)
    else:
        logger.warning("Could not extract price data for %s", match["name"])

    return result


def scrape_all():
    """Scrape all configured matches and return list of results."""
    results = []
    for match in MATCHES:
        logger.info("Scraping %s ...", match["name"])
        data = scrape_match(match)
        if data["cheapest_price"] is not None:
            logger.info(
                "  -> $%.2f | %d listings",
                data["cheapest_price"],
                data.get("total_listings") or 0,
            )
        else:
            logger.warning("  -> no price found")
        results.append(data)
    return results
