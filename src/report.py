"""
PDF report generator for the Competitor Spy Report.

Produces a 6-page branded PDF using WeasyPrint + Jinja2:
  1. Cover
  2. The Problem (score + AI analysis)
  3. Your Profile vs Competitors (suburb + LGA tables)
  4. What's This Costing You (search demand + conversion chain)
  5. Here's What Needs to Happen (action items)
  6. CTA (booking call)

Usage:
    from src.report import generate_pdf
    path = generate_pdf(report_data, "output/report.pdf")
"""

import logging
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

from src.models import Competitor, KeywordResult, ReportData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = _PROJECT_ROOT / "templates"
STATIC_DIR = _PROJECT_ROOT / "static"

# Conversion constants
TOP_3_CTR = 0.35
WEBSITE_CONVERSION = 0.20
CLOSE_RATE = 0.50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_top_competitors(result: KeywordResult, limit: int = 5) -> list[Competitor]:
    """Return the top N non-prospect competitors from a keyword result."""
    return [c for c in result.competitors if not c.is_prospect][:limit]


def _has_keyword_stuffed(competitors: list[Competitor]) -> bool:
    """Check if any competitor in the list has keyword stuffing."""
    return any(c.keyword_stuffed for c in competitors)


def _prepare_context(report_data: ReportData) -> dict:
    """Build the Jinja2 template context from ReportData."""
    lead = report_data.lead
    score = report_data.prospect_score

    # Math chain
    total_vol = report_data.total_search_volume
    potential_clicks = int(total_vol * TOP_3_CTR)
    potential_leads = int(potential_clicks * WEBSITE_CONVERSION)
    potential_jobs = int(potential_leads * CLOSE_RATE)

    # Competitors (capped at 5 each)
    suburb_comps = _get_top_competitors(report_data.suburb_result)
    lga_comps = _get_top_competitors(report_data.lga_result)

    # Check for assets
    has_phone_mockup = (STATIC_DIR / "phone-mockup.png").exists()
    has_headshot = (STATIC_DIR / "headshot.png").exists()
    has_client_logos = (STATIC_DIR / "client-logos.png").exists()

    return {
        # Lead info
        "business_name": lead.business_name,
        "contact_name": lead.contact_name,
        "trade_type": lead.trade_type,
        "suburb": lead.suburb,
        "lga": lead.lga,
        "state": lead.state,
        # Score
        "score": score.total if score else 0,
        "score_rating": score.rating if score else "N/A",
        # AI analysis
        "analysis": report_data.analysis,
        # Suburb data
        "suburb_prospect": report_data.suburb_result.prospect,
        "suburb_competitors": suburb_comps,
        "suburb_keyword": report_data.suburb_result.keyword,
        "suburb_has_stuffed": _has_keyword_stuffed(report_data.suburb_result.competitors),
        # LGA data
        "lga_prospect": report_data.lga_result.prospect,
        "lga_competitors": lga_comps,
        "lga_keyword": report_data.lga_result.keyword,
        "lga_has_stuffed": _has_keyword_stuffed(report_data.lga_result.competitors),
        # Search volume
        "keyword_volumes": report_data.keyword_volumes,
        "total_search_volume": total_vol,
        "potential_clicks": potential_clicks,
        "potential_leads": potential_leads,
        "potential_jobs": potential_jobs,
        # CTA
        "booking_url": os.environ.get("BOOKING_URL", "#"),
        "testimonials_url": os.environ.get("TESTIMONIALS_URL", "#"),
        # Assets
        "has_phone_mockup": has_phone_mockup,
        "has_headshot": has_headshot,
        "has_client_logos": has_client_logos,
        # Meta
        "date": datetime.now().strftime("%d %B %Y"),
    }


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def generate_pdf(report_data: ReportData, output_path: str) -> str:
    """Generate the full Competitor Spy Report PDF.

    Args:
        report_data: All data needed for the report (lead info, keyword
            results, score, analysis content).
        output_path: File path where the PDF will be written.

    Returns:
        The output_path string (for convenience in chaining).
    """
    logger.info(
        "Generating report for '%s' -> %s",
        report_data.lead.business_name,
        output_path,
    )

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Load and render Jinja2 template
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html.j2")

    context = _prepare_context(report_data)
    html_string = template.render(**context)

    # Configure fonts
    font_config = FontConfiguration()

    # Load CSS
    css_path = STATIC_DIR / "styles.css"
    css = CSS(filename=str(css_path), font_config=font_config)

    # Generate PDF
    # base_url points to static/ so image src="logo.png" resolves to static/logo.png
    html = HTML(
        string=html_string,
        base_url=str(STATIC_DIR) + "/",
    )

    html.write_pdf(
        output_path,
        stylesheets=[css],
        font_config=font_config,
    )

    logger.info("PDF generated successfully: %s", output_path)
    return output_path
