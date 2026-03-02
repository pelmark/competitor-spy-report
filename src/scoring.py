"""
GBP Optimisation Scoring — 9 factors, 95 points total.

Scores a single competitor or prospect based on their Google Business Profile
data relative to the area averages for their keyword.
"""

import logging
import re

from src.models import Competitor, ScoreBreakdown

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trade type → GBP category mappings
# ---------------------------------------------------------------------------
CATEGORY_MAP: dict[str, dict[str, list[str]]] = {
    "plumber": {
        "optimal": ["Plumber", "Plumbing Service"],
        "related": [
            "Drainage Service",
            "Water Heater Repair Service",
            "Bathroom Remodeler",
            "Gas Fitter",
        ],
    },
    "electrician": {
        "optimal": ["Electrician", "Electrical Installation Service"],
        "related": [
            "Lighting Contractor",
            "Solar Energy Contractor",
            "Electrical Engineer",
            "Electric Vehicle Charging Station",
        ],
    },
    "hvac": {
        "optimal": ["HVAC Contractor", "Air Conditioning Contractor"],
        "related": [
            "Heating Contractor",
            "Refrigeration Service",
        ],
    },
    "roofer": {
        "optimal": ["Roofing Contractor", "Roof Repair Service"],
        "related": [
            "Gutter Cleaning Service",
            "Metal Fabricator",
            "Building Materials Supplier",
        ],
    },
    "landscaper": {
        "optimal": ["Landscaper", "Landscaping Service"],
        "related": [
            "Lawn Care Service",
            "Garden Center",
            "Tree Service",
            "Paving Contractor",
        ],
    },
    "painter": {
        "optimal": ["Painter", "Painting Service"],
        "related": [
            "House Painter",
            "Commercial Painter",
            "Decorator",
        ],
    },
    "carpenter": {
        "optimal": ["Carpenter", "Carpentry Service"],
        "related": [
            "Cabinet Maker",
            "Joiner",
            "Deck Builder",
            "Furniture Maker",
        ],
    },
}


# ---------------------------------------------------------------------------
# Individual scoring helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase and strip excess whitespace for comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())


def detect_keyword_stuffing(business_name: str, keyword: str) -> bool:
    """Check if a business name looks keyword-stuffed.

    A name is considered stuffed when it contains 3 or more distinct keyword
    terms crammed together — e.g. "Best Plumber Cronulla Emergency Plumbing 24/7".
    """
    name_lower = _normalise(business_name)
    keyword_terms = _normalise(keyword).split()

    # Build a broader set of spammy terms related to the keyword
    spam_signals = set(keyword_terms)
    # Common padding words that stuffers add alongside real keywords
    trade_spam = {
        "best", "top", "cheap", "affordable", "emergency", "24/7",
        "fast", "local", "near", "me", "expert", "pro",
    }
    spam_signals.update(trade_spam)

    # Count how many spam/keyword terms appear in the name
    name_words = set(name_lower.split())
    matches = name_words & spam_signals

    # 3+ keyword/spam terms in the name = stuffed
    return len(matches) >= 3


def check_business_name_match(business_name: str, keyword: str) -> int:
    """Score business name relevance to the keyword.

    Returns:
        15 — exact keyword match (e.g. "Cronulla Plumbing" for "plumber cronulla")
         8 — partial match (at least one keyword term appears)
         0 — no match
    """
    name_lower = _normalise(business_name)
    keyword_terms = _normalise(keyword).split()

    # Check for exact match — all keyword terms present in the name
    if all(term in name_lower for term in keyword_terms):
        return 15

    # Check for partial match — at least one keyword term present
    if any(term in name_lower for term in keyword_terms):
        return 8

    return 0


def check_primary_category(category: str, trade_type: str) -> int:
    """Score the GBP primary category against the trade type.

    Returns:
        12 — optimal category match
         6 — related category
         0 — wrong or irrelevant
    """
    if not category:
        return 0

    trade_key = trade_type.strip().lower()
    mapping = CATEGORY_MAP.get(trade_key)

    if not mapping:
        # Unknown trade type — fall back to simple string matching
        logger.warning("No category mapping for trade type '%s', using fuzzy match", trade_type)
        if trade_key in category.lower():
            return 12
        return 0

    cat_lower = category.strip().lower()

    for optimal in mapping["optimal"]:
        if cat_lower == optimal.lower():
            return 12

    for related in mapping["related"]:
        if cat_lower == related.lower():
            return 6

    return 0


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_competitor(
    competitor: Competitor,
    keyword: str,
    trade_type: str,
    area_median_reviews: float,
    area_median_photos: float,
) -> ScoreBreakdown:
    """Score a single competitor/prospect across all 9 GBP factors.

    Args:
        competitor: The business to score.
        keyword: The search keyword (e.g. "plumber cronulla").
        trade_type: The trade category (e.g. "plumber").
        area_median_reviews: Median review count for the area.
        area_median_photos: Median photo count for the area.

    Returns:
        A ScoreBreakdown with individual factor scores (total out of 100).
    """
    score = ScoreBreakdown()

    # 1. Business Name Match (15 pts) — Extreme
    score.business_name_match = check_business_name_match(
        competitor.business_name, keyword,
    )
    # Also flag keyword stuffing on the competitor object
    if detect_keyword_stuffing(competitor.business_name, keyword):
        competitor.keyword_stuffed = True
        logger.info(
            "Keyword stuffing detected: '%s'", competitor.business_name,
        )

    # 2. Website (12 pts) — Extreme
    score.website = 12 if competitor.has_website else 0

    # 3. Address Type (12 pts) — Extreme
    addr = competitor.address_type.strip().lower()
    if addr == "physical":
        score.address_type = 12
    elif addr == "sab":
        score.address_type = 6
    else:
        score.address_type = 0

    # 4. Primary Category (12 pts) — Extreme
    score.primary_category = check_primary_category(
        competitor.primary_category, trade_type,
    )

    # 5. Review Average (10 pts) — High
    if competitor.star_rating >= 4.5:
        score.review_average = 10
    elif competitor.star_rating >= 4.0:
        score.review_average = 6
    else:
        score.review_average = 2

    # 6. Review Count (10 pts) — High
    score.review_count = 10 if competitor.review_count >= area_median_reviews else 3

    # 7. Photos (12 pts) — High
    score.photos = 12 if competitor.photo_count >= area_median_photos else 3

    # 8. Organic Top 10 (5 pts) — High
    score.organic_top_10 = 5 if competitor.organic_top_10 else 0

    # 9. Description (7 pts) — Medium
    score.description = 7 if competitor.has_description else 0

    logger.debug(
        "Scored '%s': %d/100 (%s)",
        competitor.business_name,
        score.total,
        score.rating,
    )

    return score
