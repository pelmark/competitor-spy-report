"""
Data models for the Competitor Spy Report.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LeadInput:
    """Input data from the Facebook Lead Form via GHL."""
    trade_type: str
    business_name: str
    contact_name: str
    email: str
    phone: str
    suburb: str
    lga: str
    state: str = "NSW"
    website_url: Optional[str] = None  # None = "I don't have a website"


@dataclass
class Competitor:
    """A single competitor's GBP data."""
    business_name: str
    # Rankings
    maps_top_3: bool = False
    maps_position: Optional[int] = None
    organic_top_10: bool = False
    organic_position: Optional[int] = None
    # GBP details
    website: Optional[str] = None
    has_website: bool = False
    address_type: str = "unknown"  # "physical" or "sab"
    primary_category: str = ""
    star_rating: float = 0.0
    review_count: int = 0
    photo_count: int = 0
    has_description: bool = False
    has_services: bool = False
    has_products: bool = False
    # Metadata
    place_id: Optional[str] = None
    maps_url: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    is_prospect: bool = False  # True if this is the prospect's own business
    keyword_stuffed: bool = False  # Flag for spam policy violation


@dataclass
class ScoreBreakdown:
    """Individual score for each of the 9 factors."""
    business_name_match: int = 0
    website: int = 0
    address_type: int = 0
    primary_category: int = 0
    review_average: int = 0
    review_count: int = 0
    photos: int = 0
    organic_top_10: int = 0
    description: int = 0

    @property
    def total(self) -> int:
        return (
            self.business_name_match
            + self.website
            + self.address_type
            + self.primary_category
            + self.review_average
            + self.review_count
            + self.photos
            + self.organic_top_10
            + self.description
        )

    @property
    def rating(self) -> str:
        score = self.total
        if score >= 80:
            return "Excellent"
        elif score >= 60:
            return "Good"
        elif score >= 40:
            return "Average"
        elif score >= 20:
            return "Weak"
        else:
            return "Poor"

    @property
    def rating_description(self) -> str:
        score = self.total
        if score >= 80:
            return "Highly optimized, strong competitor"
        elif score >= 60:
            return "Solid profile, some gaps"
        elif score >= 40:
            return "Meaningful optimization opportunities"
        elif score >= 20:
            return "Significant gaps across multiple factors"
        else:
            return "Minimal GBP presence"


@dataclass
class KeywordResult:
    """Results for a single keyword search (suburb or LGA level)."""
    keyword: str  # e.g. "plumber Cronulla"
    location: str  # e.g. "Cronulla" or "Sutherland Shire"
    level: str  # "suburb" or "lga"
    competitors: list[Competitor] = field(default_factory=list)
    prospect: Optional[Competitor] = None  # The prospect's business if found

    @property
    def area_avg_reviews(self) -> float:
        counts = [c.review_count for c in self.competitors if not c.is_prospect]
        if not counts:
            return 0
        counts.sort()
        mid = len(counts) // 2
        if len(counts) % 2 == 0:
            return (counts[mid - 1] + counts[mid]) / 2
        return float(counts[mid])

    @property
    def area_avg_rating(self) -> float:
        ratings = [c.star_rating for c in self.competitors if not c.is_prospect and c.star_rating > 0]
        if not ratings:
            return 0
        return sum(ratings) / len(ratings)

    @property
    def area_avg_photos(self) -> float:
        counts = [c.photo_count for c in self.competitors if not c.is_prospect]
        if not counts:
            return 0
        counts.sort()
        mid = len(counts) // 2
        if len(counts) % 2 == 0:
            return (counts[mid - 1] + counts[mid]) / 2
        return float(counts[mid])

    @property
    def competitors_with_website(self) -> int:
        return sum(1 for c in self.competitors if c.has_website and not c.is_prospect)

    @property
    def total_competitors(self) -> int:
        return sum(1 for c in self.competitors if not c.is_prospect)


@dataclass
class KeywordVolume:
    """Search volume for a single keyword."""
    keyword: str
    search_volume: int = 0  # Average monthly searches


@dataclass
class AnalysisContent:
    """Structured AI-generated content for multiple report pages."""
    # Page 2 — "The problem"
    score_explanation: str = ""
    pattern_interrupt: str = ""
    competitors_doing_right: list[str] = field(default_factory=list)
    falling_behind: list[str] = field(default_factory=list)
    # Page 4 — "What's this costing you"
    search_framing: str = ""
    math_chain: str = ""
    provocative_close: str = ""
    # Page 5 — "Here's what needs to happen"
    action_items: list[dict] = field(default_factory=list)  # [{name, explanation}]
    closing_bridge: str = ""


@dataclass
class ReportData:
    """All data needed to generate the full PDF report."""
    lead: LeadInput
    suburb_result: KeywordResult
    lga_result: KeywordResult
    prospect_score: Optional[ScoreBreakdown] = None
    analysis: Optional[AnalysisContent] = None
    keyword_volumes: list[KeywordVolume] = field(default_factory=list)

    @property
    def total_search_volume(self) -> int:
        return sum(kv.search_volume for kv in self.keyword_volumes)
