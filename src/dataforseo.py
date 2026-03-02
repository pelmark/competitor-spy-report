"""
DataForSEO API client for the Competitor Spy Report.

Handles all API interactions: Maps SERP, Organic SERP, Place Details lookups,
and keyword search volume. Orchestrates searches and returns populated
KeywordResult objects with Competitor data.
"""

import logging
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.models import Competitor, KeywordResult, KeywordVolume, LeadInput, ReportData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://api.dataforseo.com/v3"

# How many Maps results to pull back (top 20 covers local pack + extras)
MAPS_DEPTH = 20

# How many organic results to consider
ORGANIC_DEPTH = 10

# Pause between API calls to stay well within rate limits
REQUEST_DELAY_SECONDS = 0.5

# Maximum number of place-detail lookups per keyword (controls cost)
MAX_PLACE_DETAIL_LOOKUPS = 10

# Words that signal keyword stuffing when they appear in a GBP business name
# alongside the trade term. e.g. "Sydney Emergency Plumber 24/7 Hot Water"
KEYWORD_STUFF_SIGNALS = [
    "24/7", "24 hour", "emergency", "near me", "best", "cheap",
    "affordable", "top", "local", "fast", "same day", "same-day",
    "hot water", "blocked drain", "gas fitter", "solar",
    "air conditioning", "aircon", "hvac", "heating", "cooling",
]


# ---------------------------------------------------------------------------
# Session / auth helpers
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[str, str]:
    """Read DataForSEO credentials from environment variables."""
    login = os.environ.get("DATAFORSEO_LOGIN")
    password = os.environ.get("DATAFORSEO_PASSWORD")
    if not login or not password:
        raise EnvironmentError(
            "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD environment variables "
            "must be set."
        )
    return login, password


def _build_session() -> requests.Session:
    """
    Build a requests Session with Basic Auth, retries, and timeouts.
    """
    login, password = _get_credentials()
    session = requests.Session()
    session.auth = (login, password)
    session.headers.update({
        "Content-Type": "application/json",
    })

    # Retry on transient server errors and rate limits
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


# Module-level session (lazy-initialised)
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


# ---------------------------------------------------------------------------
# Low-level API call
# ---------------------------------------------------------------------------

def _api_post(endpoint: str, payload: list[dict]) -> dict:
    """
    Make a POST request to a DataForSEO endpoint.

    Args:
        endpoint: Path relative to BASE_URL (e.g. "/serp/google/maps/live/advanced").
        payload: List of task objects to send.

    Returns:
        Parsed JSON response dict.

    Raises:
        requests.HTTPError: On non-2xx responses after retries.
    """
    url = f"{BASE_URL}{endpoint}"
    session = _get_session()

    logger.debug("POST %s — payload keys: %s", url, [list(p.keys()) for p in payload])

    response = session.post(url, json=payload, timeout=60)
    response.raise_for_status()

    data = response.json()

    # DataForSEO wraps errors in status_code / status_message at the top level
    status_code = data.get("status_code")
    if status_code and status_code != 20000:
        logger.error(
            "DataForSEO API error %s: %s",
            status_code,
            data.get("status_message", "unknown"),
        )

    return data


# ---------------------------------------------------------------------------
# Maps SERP
# ---------------------------------------------------------------------------

def search_maps(keyword: str, location_name: str = "Australia") -> list[dict]:
    """
    Search Google Maps SERP for a keyword.

    Args:
        keyword: Full search term, e.g. "plumber Cronulla NSW Australia".
        location_name: DataForSEO location_name (country or region).

    Returns:
        List of raw Maps result items.
    """
    logger.info("Maps SERP search: '%s' (location: %s)", keyword, location_name)

    payload = [{
        "keyword": keyword,
        "location_name": location_name,
        "language_code": "en",
        "device": "desktop",
        "os": "windows",
        "depth": MAPS_DEPTH,
    }]

    try:
        data = _api_post("/serp/google/maps/live/advanced", payload)
    except requests.RequestException as exc:
        logger.error("Maps SERP request failed for '%s': %s", keyword, exc)
        return []

    try:
        items = data["tasks"][0]["result"][0]["items"] or []
    except (KeyError, IndexError, TypeError):
        logger.warning("No Maps items returned for '%s'", keyword)
        return []

    logger.info("Maps SERP returned %d items for '%s'", len(items), keyword)
    return items


# ---------------------------------------------------------------------------
# Organic SERP
# ---------------------------------------------------------------------------

def search_organic(keyword: str, location_name: str = "Australia") -> list[dict]:
    """
    Search Google Organic SERP for a keyword.

    Returns a list of organic result items.
    """
    logger.info("Organic SERP search: '%s' (location: %s)", keyword, location_name)

    payload = [{
        "keyword": keyword,
        "location_name": location_name,
        "language_code": "en",
        "device": "desktop",
        "os": "windows",
    }]

    try:
        data = _api_post("/serp/google/organic/live/advanced", payload)
    except requests.RequestException as exc:
        logger.error("Organic SERP request failed for '%s': %s", keyword, exc)
        return []

    try:
        all_items = data["tasks"][0]["result"][0]["items"] or []
    except (KeyError, IndexError, TypeError):
        logger.warning("No organic items returned for '%s'", keyword)
        return []

    organic_items = [i for i in all_items if i.get("type") == "organic"]
    logger.info(
        "Organic SERP returned %d organic items for '%s'",
        len(organic_items), keyword,
    )

    return organic_items


def _domain_from_url(url: str) -> str:
    """Extract bare domain from a URL (strip www.)."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Maps item field parsers
# ---------------------------------------------------------------------------

def _parse_rating(item: dict) -> float:
    """
    Extract star rating from a Maps SERP item.

    DataForSEO may return rating as:
      - A dict: {"value": 4.8, "votes_count": 123, ...}
      - A direct float/int
      - None
    """
    rating_raw = item.get("rating")
    if isinstance(rating_raw, dict):
        return float(rating_raw.get("value", 0) or 0)
    if isinstance(rating_raw, (int, float)):
        return float(rating_raw)
    return 0.0


def _parse_review_count(item: dict) -> int:
    """
    Extract review count from a Maps SERP item.

    Checks top-level reviews_count first, then falls back to
    rating.votes_count if rating is a dict.
    """
    # Top-level field (most common)
    reviews = item.get("reviews_count")
    if isinstance(reviews, int) and reviews > 0:
        return reviews

    # Fallback: nested in rating dict
    rating_raw = item.get("rating")
    if isinstance(rating_raw, dict):
        votes = rating_raw.get("votes_count", 0)
        if isinstance(votes, int):
            return votes

    return 0


# ---------------------------------------------------------------------------
# Place Details
# ---------------------------------------------------------------------------

def get_place_details(place_id: str, business_name: str = "", location: str = "Australia") -> dict:
    """
    Get Google Business Profile details for a single place_id.

    Returns a dict with keys: photos_count, description, services, products,
    address_type, primary_category (or sensible defaults on failure).
    """
    logger.debug("Fetching place details for place_id=%s (%s)", place_id, business_name)

    # The my_business_info endpoint needs keyword + location.
    # place_id can be passed as "place_id:{id}" in the keyword field.
    keyword = f"place_id:{place_id}" if place_id else business_name

    payload = [{
        "keyword": keyword,
        "location_name": location,
        "language_code": "en",
    }]

    defaults = {
        "photos_count": 0,
        "description": None,
        "services": [],
        "products": [],
        "address_type": "unknown",
        "primary_category": "",
    }

    try:
        data = _api_post("/business_data/google/my_business_info/live", payload)
    except requests.RequestException as exc:
        logger.warning("Place details request failed for %s: %s", place_id, exc)
        return defaults

    try:
        result_list = data["tasks"][0]["result"] or []
        if not result_list:
            logger.warning("Empty result for place_id=%s", place_id)
            return defaults

        # Response structure: tasks[0].result[0] is a wrapper with keys:
        # keyword, se_domain, location_code, items_count, items
        # The actual business data is in result[0].items[0]
        wrapper = result_list[0]
        nested_items = wrapper.get("items") or []
        if not nested_items:
            logger.warning("No nested items in place detail for %s (items_count=%s)",
                          place_id, wrapper.get("items_count"))
            return defaults
        info = nested_items[0]
    except (KeyError, IndexError, TypeError):
        logger.warning("No place detail data for %s", place_id)
        return defaults

    # Log the raw keys so we can see what's actually coming back
    logger.info("Place detail keys for %s: %s", place_id, list(info.keys()))
    logger.info("Place detail sample for %s: total_photos=%s, description=%s, category=%s, address=%s",
                place_id, info.get("total_photos"), info.get("description", "")[:50] if info.get("description") else None,
                info.get("category"), info.get("address"))

    # Photos: field is "total_photos" in the response
    photos_count = 0
    for field in ("total_photos", "photos_count", "media_count"):
        val = info.get(field)
        if isinstance(val, int) and val > 0:
            photos_count = val
            break

    # Address type: physical address vs SAB
    address_type = "unknown"
    address = info.get("address") or ""
    address_info = info.get("address_info") or {}
    if address or address_info.get("address"):
        address_type = "physical"
    else:
        address_type = "sab"

    # Description: try "description" then "snippet"
    description = info.get("description") or info.get("snippet") or None

    # Services and products: might be nested or flat lists
    services = info.get("services") or info.get("service_offerings") or []
    products = info.get("products") or info.get("product_offerings") or []

    # Category
    primary_category = info.get("category") or info.get("primary_category") or ""

    result = {
        "photos_count": photos_count,
        "description": description,
        "services": services,
        "products": products,
        "address_type": address_type,
        "primary_category": primary_category,
    }

    logger.info(
        "Place details for %s: %d photos, desc=%s, services=%s, products=%s, addr=%s, cat=%s",
        place_id, photos_count, bool(description), bool(services),
        bool(products), address_type, primary_category,
    )
    return result


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _is_prospect_match(candidate_name: str, prospect_name: str) -> bool:
    """
    Check if a Maps/organic result name matches the prospect's business.

    Uses case-insensitive partial matching: either name contains the other,
    or every word of the shorter name appears in the longer one.
    """
    a = _normalise(candidate_name)
    b = _normalise(prospect_name)

    if not a or not b:
        return False

    # Direct containment
    if a in b or b in a:
        return True

    # Word overlap: all words from the shorter string present in the longer
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    short_words = set(short.split())
    long_words = set(long.split())

    if short_words and short_words.issubset(long_words):
        return True

    return False


# ---------------------------------------------------------------------------
# Keyword stuffing detection
# ---------------------------------------------------------------------------

def _is_keyword_stuffed(business_name: str, trade_type: str = "") -> bool:
    """
    Heuristic: flag business names that pack in extra keywords beyond the
    actual business name. Common GBP spam tactic.

    Signals:
      - Name contains 4+ separate "words" that are also common service keywords
      - Name contains a pipe | or dash-separated keyword list
      - Name contains location + service combos like "Sydney Plumber Emergency 24/7"
    """
    name_lower = business_name.lower()

    # Pipe or heavy separator abuse
    if "|" in business_name or " - " in business_name:
        parts = re.split(r"[|\-]", business_name)
        if len(parts) >= 3:
            return True

    # Count how many signal phrases appear in the name
    matches = sum(1 for signal in KEYWORD_STUFF_SIGNALS if signal in name_lower)
    if matches >= 2:
        return True

    # Unusually long business names (more than 6 "words") are suspicious
    word_count = len(business_name.split())
    if word_count >= 7:
        return True

    return False


def _apply_place_details(comp: Competitor, details: dict) -> None:
    """Apply place detail enrichment data onto a competitor."""
    # Photos: use place details if Maps didn't give us a count, or if higher
    if details["photos_count"] > 0 and comp.photo_count == 0:
        comp.photo_count = details["photos_count"]
    if details["photos_count"] > comp.photo_count:
        comp.photo_count = details["photos_count"]

    # Description: place details is more reliable than Maps snippet
    if details["description"]:
        comp.has_description = True

    # Services and products: only from place details
    if details["services"]:
        comp.has_services = True
    if details["products"]:
        comp.has_products = True

    # Address type: prefer place details over Maps guess
    if details["address_type"] != "unknown":
        comp.address_type = details["address_type"]

    # Category: prefer place details if we don't have one
    if details["primary_category"] and not comp.primary_category:
        comp.primary_category = details["primary_category"]


# ---------------------------------------------------------------------------
# Keyword Search Volume
# ---------------------------------------------------------------------------

def get_keyword_volumes(
    keywords: list[str],
    location_name: str = "Australia",
) -> list[KeywordVolume]:
    """
    Fetch average monthly search volume for a list of keywords.

    Uses the Google Ads Search Volume endpoint. All keywords are sent in a
    single API call to minimise cost.

    Args:
        keywords: List of search terms (e.g. ["plumber cronulla", "emergency plumber cronulla"]).
        location_name: DataForSEO location_name (default "Australia").

    Returns:
        List of KeywordVolume objects with search_volume populated.
    """
    logger.info("Fetching search volume for %d keywords: %s", len(keywords), keywords)

    payload = [{
        "keywords": keywords,
        "location_name": location_name,
        "language_code": "en",
    }]

    try:
        data = _api_post("/keywords_data/google_ads/search_volume/live", payload)
    except requests.RequestException as exc:
        logger.error("Keyword volume request failed: %s", exc)
        return [KeywordVolume(keyword=kw, search_volume=0) for kw in keywords]

    try:
        results = data["tasks"][0]["result"] or []
    except (KeyError, IndexError, TypeError):
        logger.warning("No keyword volume results returned")
        return [KeywordVolume(keyword=kw, search_volume=0) for kw in keywords]

    volumes = []
    for item in results:
        kw = item.get("keyword", "")
        vol = item.get("search_volume") or 0
        volumes.append(KeywordVolume(keyword=kw, search_volume=vol))
        logger.info("Search volume: '%s' = %d/mo", kw, vol)

    return volumes


# ---------------------------------------------------------------------------
# Orchestration: single keyword
# ---------------------------------------------------------------------------

def search_keyword(
    keyword: str,
    location_name: str,
    prospect_name: str,
    level: str = "suburb",
    location_label: str = "",
    trade_type: str = "",
) -> KeywordResult:
    """
    Run all API calls for a single keyword and return a populated KeywordResult.

    Steps:
        1. Maps SERP -> competitor list with rankings, ratings, reviews
        2. Organic SERP -> organic positions
        3. Place Details -> enrich top competitors with photos, services, etc.
        4. Match the prospect's business and flag it

    Args:
        keyword: Full search query (e.g. "plumber Cronulla NSW Australia").
        location_name: DataForSEO location_name (e.g. "Australia").
        prospect_name: The prospect's business name for matching.
        level: "suburb" or "lga".
        location_label: Human-readable location (e.g. "Cronulla").
        trade_type: The trade/service type for keyword-stuffing detection.

    Returns:
        A populated KeywordResult.
    """
    logger.info(
        "=== Searching keyword: '%s' (level=%s, prospect='%s') ===",
        keyword, level, prospect_name,
    )

    result = KeywordResult(
        keyword=keyword,
        location=location_label or keyword,
        level=level,
    )

    # ------------------------------------------------------------------
    # 1. Maps SERP
    # ------------------------------------------------------------------
    maps_items = search_maps(keyword, location_name)
    time.sleep(REQUEST_DELAY_SECONDS)

    # Build a dict of competitors keyed by normalised name for dedup
    competitors_by_name: dict[str, Competitor] = {}

    for idx, item in enumerate(maps_items):
        title = item.get("title") or ""
        if not title:
            continue

        # Log the first item's keys so we can see the actual response structure
        if idx == 0:
            logger.info("Maps item keys: %s", list(item.keys()))
            logger.info("Maps item sample: title=%s, category=%s, total_photos=%s, rating=%s, address=%s",
                        item.get("title"), item.get("category"), item.get("total_photos"),
                        item.get("rating"), item.get("address"))

        position = idx + 1
        place_id = item.get("place_id")
        # Maps SERP: "url" is usually the GMB/Maps URL, "domain" is the website domain
        website = item.get("domain") or item.get("url")
        is_prospect = _is_prospect_match(title, prospect_name)

        # Parse rating — DataForSEO returns a dict with value + votes_count
        star_rating = _parse_rating(item)
        review_count = _parse_review_count(item)

        # Photos: Maps SERP returns total_photos directly
        photo_count = item.get("total_photos") or 0

        # Category: Maps SERP returns "category" (primary) + "additional_categories"
        primary_category = item.get("category") or ""

        # Address type: if address field is populated, it's physical.
        # SABs typically have no street address in Maps results.
        address = item.get("address") or ""
        address_type = "physical" if address else "sab"

        # Snippet sometimes contains description-like info
        snippet = item.get("snippet") or ""
        has_description = bool(snippet and len(snippet) > 10)

        comp = Competitor(
            business_name=title,
            maps_top_3=(position <= 3),
            maps_position=position,
            website=website,
            has_website=bool(website),
            star_rating=star_rating,
            review_count=review_count,
            photo_count=photo_count,
            place_id=place_id,
            maps_url=item.get("url"),
            phone=item.get("phone"),
            address=address,
            address_type=address_type,
            primary_category=primary_category,
            has_description=has_description,
            is_prospect=is_prospect,
            keyword_stuffed=_is_keyword_stuffed(title, trade_type),
        )

        competitors_by_name[_normalise(title)] = comp

    # ------------------------------------------------------------------
    # 2. Organic SERP
    # ------------------------------------------------------------------
    organic_items = search_organic(keyword, location_name)
    time.sleep(REQUEST_DELAY_SECONDS)

    # Merge organic positions into existing competitors or create new ones
    for item in organic_items[:ORGANIC_DEPTH]:
        position = item.get("rank_absolute") or item.get("position")
        title = item.get("title") or ""
        domain = item.get("domain") or _domain_from_url(item.get("url", ""))
        url = item.get("url")

        # Try to match to an existing Maps competitor by name or website domain
        matched_key = _find_matching_competitor(
            title, domain, competitors_by_name
        )

        if matched_key:
            comp = competitors_by_name[matched_key]
            if position is not None:
                comp.organic_position = int(position)
                comp.organic_top_10 = int(position) <= 10
            if not comp.website and url:
                comp.website = url
                comp.has_website = True
        else:
            # Organic-only competitor (not in Maps)
            is_prospect = _is_prospect_match(title, prospect_name)
            comp = Competitor(
                business_name=title,
                organic_position=int(position) if position else None,
                organic_top_10=(int(position) <= 10) if position else False,
                website=url,
                has_website=bool(url),
                is_prospect=is_prospect,
                keyword_stuffed=_is_keyword_stuffed(title, trade_type),
            )
            competitors_by_name[_normalise(title)] = comp

    # ------------------------------------------------------------------
    # 3. Place Details enrichment (top N Maps results only)
    # ------------------------------------------------------------------
    # Always enrich the prospect + top N competitors
    prospect_comp = None
    for key, comp in competitors_by_name.items():
        if comp.is_prospect:
            prospect_comp = comp
            break

    place_ids_fetched = 0
    enriched_keys: set[str] = set()

    # Enrich prospect first (always, regardless of position)
    if prospect_comp and prospect_comp.place_id:
        time.sleep(REQUEST_DELAY_SECONDS)
        details = get_place_details(prospect_comp.place_id, prospect_comp.business_name, location_name)
        place_ids_fetched += 1
        enriched_keys.add(_normalise(prospect_comp.business_name))
        _apply_place_details(prospect_comp, details)

    # Then enrich top N competitors
    for key, comp in competitors_by_name.items():
        if place_ids_fetched >= MAX_PLACE_DETAIL_LOOKUPS:
            break
        if not comp.place_id:
            continue
        if key in enriched_keys:
            continue

        time.sleep(REQUEST_DELAY_SECONDS)
        details = get_place_details(comp.place_id, comp.business_name, location_name)
        place_ids_fetched += 1
        _apply_place_details(comp, details)

    # ------------------------------------------------------------------
    # 4. Assemble result
    # ------------------------------------------------------------------
    all_competitors = list(competitors_by_name.values())

    # Sort: Maps position first (nulls last), then organic position
    all_competitors.sort(
        key=lambda c: (
            c.maps_position if c.maps_position is not None else 9999,
            c.organic_position if c.organic_position is not None else 9999,
        )
    )

    result.competitors = all_competitors

    # Identify the prospect
    prospects = [c for c in all_competitors if c.is_prospect]
    if prospects:
        result.prospect = prospects[0]
        logger.info(
            "Prospect '%s' found — Maps #%s, Organic #%s",
            result.prospect.business_name,
            result.prospect.maps_position,
            result.prospect.organic_position,
        )
    else:
        logger.info("Prospect '%s' NOT found in results for '%s'", prospect_name, keyword)

    logger.info(
        "Keyword '%s' complete: %d competitors, prospect_found=%s",
        keyword, len(all_competitors), result.prospect is not None,
    )

    return result


def _find_matching_competitor(
    title: str,
    domain: str,
    competitors: dict[str, "Competitor"],
) -> Optional[str]:
    """
    Try to match an organic result to an existing Maps competitor by domain
    first (most reliable), then by name.

    Returns the competitor dict key if matched, else None.
    """
    # Domain match is the most reliable — organic URL domain matches Maps website
    if domain:
        for key, comp in competitors.items():
            comp_domain = _domain_from_url(comp.website) if comp.website else ""
            if comp_domain and comp_domain == domain:
                return key

    norm_title = _normalise(title)

    # Exact normalised name match
    if norm_title in competitors:
        return norm_title

    # Partial name match — organic page titles often differ from GMB names
    # so we check if the business name appears within the organic title
    if norm_title:
        for key, comp in competitors.items():
            comp_norm = _normalise(comp.business_name)
            if comp_norm and (comp_norm in norm_title or norm_title in comp_norm):
                return key

    return None


# ---------------------------------------------------------------------------
# Orchestration: full report
# ---------------------------------------------------------------------------

def generate_report_data(lead: LeadInput) -> ReportData:
    """
    Run searches for both the suburb-level and LGA-level keywords and
    return a fully populated ReportData.

    Constructs keywords as: "{trade_type} {suburb} {state} Australia"
    and "{trade_type} {lga} {state} Australia".

    Args:
        lead: The lead input containing trade type, location, and business info.

    Returns:
        A ReportData with suburb_result and lga_result populated.
    """
    logger.info(
        "Generating report data for '%s' (%s) in %s / %s",
        lead.business_name, lead.trade_type, lead.suburb, lead.lga,
    )

    suburb_keyword = f"{lead.trade_type} {lead.suburb}"
    lga_keyword = f"{lead.trade_type} {lead.lga}"

    suburb_result = search_keyword(
        keyword=suburb_keyword,
        location_name="Australia",
        prospect_name=lead.business_name,
        level="suburb",
        location_label=lead.suburb,
        trade_type=lead.trade_type,
    )

    lga_result = search_keyword(
        keyword=lga_keyword,
        location_name="Australia",
        prospect_name=lead.business_name,
        level="lga",
        location_label=lead.lga,
        trade_type=lead.trade_type,
    )

    # Fetch search volume for the 4 keyword combinations
    volume_keywords = [
        suburb_keyword,
        lga_keyword,
        f"emergency {suburb_keyword}",
        f"emergency {lga_keyword}",
    ]
    time.sleep(REQUEST_DELAY_SECONDS)
    keyword_volumes = get_keyword_volumes(volume_keywords, "Australia")

    report = ReportData(
        lead=lead,
        suburb_result=suburb_result,
        lga_result=lga_result,
        keyword_volumes=keyword_volumes,
    )

    logger.info(
        "Report data complete. Suburb: %d competitors (prospect=%s). "
        "LGA: %d competitors (prospect=%s).",
        len(suburb_result.competitors),
        suburb_result.prospect is not None,
        len(lga_result.competitors),
        lga_result.prospect is not None,
    )

    return report
