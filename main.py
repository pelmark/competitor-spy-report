"""
Competitor Spy Report — Flask entry point.

Exposes two endpoints:
  GET  /health           — liveness check
  POST /generate-report  — full pipeline: DataForSEO → scoring → analysis → PDF
"""

import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file

from src.analysis import generate_analysis
from src.dataforseo import generate_report_data
from src.models import LeadInput
from src.report import generate_pdf
from src.scoring import score_competitor

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    "trade_type",
    "business_name",
    "contact_name",
    "email",
    "phone",
    "suburb",
    "lga",
]

OUTPUT_DIR = Path(__file__).parent / "output"

# Delete PDFs older than this many seconds on each request (0 = disabled)
PDF_MAX_AGE_SECONDS = 60 * 60 * 24  # 24 hours


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert a business name to a safe filename fragment.

    e.g. "Tom's Electrical & Plumbing Co." → "toms-electrical-plumbing-co"
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)   # strip special chars (keep hyphens)
    text = re.sub(r"[\s_]+", "-", text)    # spaces/underscores → hyphens
    text = re.sub(r"-{2,}", "-", text)     # collapse multiple hyphens
    text = text.strip("-")
    return text or "report"


def _check_auth() -> bool:
    """Return True if the request passes auth, or if auth is not configured."""
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        return True  # auth not configured — open access

    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {secret}":
        return True

    log.warning(
        "Unauthorised request from %s — bad or missing Bearer token",
        request.remote_addr,
    )
    return False


def _cleanup_old_pdfs() -> None:
    """Remove PDFs from the output directory that are older than PDF_MAX_AGE_SECONDS."""
    if PDF_MAX_AGE_SECONDS <= 0:
        return

    now = time.time()
    removed = 0

    try:
        for pdf in OUTPUT_DIR.glob("*.pdf"):
            age = now - pdf.stat().st_mtime
            if age > PDF_MAX_AGE_SECONDS:
                pdf.unlink(missing_ok=True)
                removed += 1
    except Exception:
        log.exception("Error during PDF cleanup (non-fatal)")

    if removed:
        log.info("Cleaned up %d old PDF(s) from output/", removed)


def _find_prospect(report_data, lead: LeadInput):
    """Return the prospect Competitor object from suburb_result, falling back to lga_result."""
    if report_data.suburb_result.prospect:
        return report_data.suburb_result.prospect
    if report_data.lga_result.prospect:
        return report_data.lga_result.prospect
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.post("/generate-report")
def generate_report():
    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    if not _check_auth():
        return jsonify({"error": "Unauthorised"}), 401

    # ------------------------------------------------------------------
    # Parse + validate input
    # ------------------------------------------------------------------
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400

    missing = [f for f in REQUIRED_FIELDS if not body.get(f)]
    if missing:
        return jsonify({
            "error": "Missing required fields",
            "fields": missing,
        }), 422

    lead = LeadInput(
        trade_type=body["trade_type"].strip().lower(),
        business_name=body["business_name"].strip(),
        contact_name=body["contact_name"].strip(),
        email=body["email"].strip(),
        phone=body["phone"].strip(),
        suburb=body["suburb"].strip(),
        lga=body["lga"].strip(),
        state=body.get("state", "NSW").strip(),
        website_url=body.get("website_url") or None,
    )

    log.info(
        "Report requested — business='%s', trade=%s, suburb=%s, lga=%s",
        lead.business_name, lead.trade_type, lead.suburb, lead.lga,
    )

    pipeline_start = time.monotonic()

    # ------------------------------------------------------------------
    # 1. DataForSEO — fetch suburb + LGA competitive landscape
    # ------------------------------------------------------------------
    try:
        t0 = time.monotonic()
        report_data = generate_report_data(lead)
        log.info("DataForSEO complete in %.1fs", time.monotonic() - t0)
    except Exception:
        log.exception("DataForSEO pipeline failed")
        return jsonify({"error": "Failed to retrieve competitor data"}), 502

    # ------------------------------------------------------------------
    # 2. Score the prospect
    # ------------------------------------------------------------------
    prospect = _find_prospect(report_data, lead)

    if prospect is None:
        # Prospect not found in any results — score a blank Competitor so
        # the report still generates (all zeros, legitimate outcome).
        from src.models import Competitor
        log.warning(
            "Prospect '%s' not found in any search results — scoring empty profile",
            lead.business_name,
        )
        prospect = Competitor(business_name=lead.business_name)

    suburb_result = report_data.suburb_result
    keyword = suburb_result.keyword

    try:
        t0 = time.monotonic()
        prospect_score = score_competitor(
            competitor=prospect,
            keyword=keyword,
            trade_type=lead.trade_type,
            area_median_reviews=suburb_result.area_avg_reviews,
            area_median_photos=suburb_result.area_avg_photos,
        )
        log.info(
            "Scoring complete in %.2fs — %d/100 (%s)",
            time.monotonic() - t0,
            prospect_score.total,
            prospect_score.rating,
        )
    except Exception:
        log.exception("Scoring failed")
        return jsonify({"error": "Failed to score competitor profile"}), 500

    # ------------------------------------------------------------------
    # 3. AI analysis
    # ------------------------------------------------------------------
    # Compute math chain before Claude call so Opus can reference real figures
    total_vol = report_data.total_search_volume
    potential_clicks = int(total_vol * 0.35)
    potential_leads = int(potential_clicks * 0.20)
    potential_jobs = int(potential_leads * 0.50)

    try:
        t0 = time.monotonic()
        analysis = generate_analysis(
            report_data, prospect_score,
            total_vol=total_vol,
            potential_clicks=potential_clicks,
            potential_leads=potential_leads,
            potential_jobs=potential_jobs,
        )
        log.info("Analysis complete in %.1fs", time.monotonic() - t0)
    except Exception:
        log.exception("Analysis generation failed")
        return jsonify({"error": "Failed to generate analysis"}), 500

    # ------------------------------------------------------------------
    # 4. Attach score + analysis to report data
    # ------------------------------------------------------------------
    report_data.prospect_score = prospect_score
    report_data.analysis = analysis

    # ------------------------------------------------------------------
    # 5. Generate PDF
    # ------------------------------------------------------------------
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(lead.business_name)
    output_path = OUTPUT_DIR / f"{timestamp}_{slug}.pdf"

    try:
        t0 = time.monotonic()
        generate_pdf(report_data, str(output_path))
        log.info("PDF generated in %.1fs → %s", time.monotonic() - t0, output_path.name)
    except Exception:
        log.exception("PDF generation failed")
        return jsonify({"error": "Failed to generate PDF report"}), 500

    # ------------------------------------------------------------------
    # 6. Deliver via GHL (if contact_id provided)
    # ------------------------------------------------------------------
    contact_id = body.get("contact_id")
    if contact_id:
        from src.ghl import upload_pdf, send_report_email

        try:
            t0 = time.monotonic()
            pdf_url = upload_pdf(contact_id, str(output_path), output_path.name)
            send_report_email(
                contact_id=contact_id,
                email=lead.email,
                contact_name=lead.contact_name,
                business_name=lead.business_name,
                pdf_url=pdf_url,
                filename=output_path.name,
            )
            log.info("GHL email sent in %.1fs", time.monotonic() - t0)
        except Exception:
            log.exception("GHL delivery failed")
            return jsonify({"error": "Report generated but failed to email via GHL"}), 502

        total_elapsed = time.monotonic() - pipeline_start
        log.info(
            "Pipeline complete for '%s' in %.1fs total (emailed via GHL)",
            lead.business_name, total_elapsed,
        )

        _cleanup_old_pdfs()
        return jsonify({"status": "ok", "message": "Report emailed to lead"}), 200

    # ------------------------------------------------------------------
    # 7. Fallback: return PDF file directly (no contact_id)
    # ------------------------------------------------------------------
    total_elapsed = time.monotonic() - pipeline_start
    log.info(
        "Pipeline complete for '%s' in %.1fs total",
        lead.business_name, total_elapsed,
    )

    _cleanup_old_pdfs()

    return send_file(
        str(output_path),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=output_path.name,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = bool(os.environ.get("FLASK_DEBUG"))

    log.info("Starting Competitor Spy Report API on port %d (debug=%s)", port, debug)

    app.run(host="0.0.0.0", port=port, debug=debug)
