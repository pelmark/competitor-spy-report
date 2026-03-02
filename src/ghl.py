"""
Go High Level API client for delivering PDF reports via email.

Uploads the generated PDF to GHL's conversation system, then sends
an email to the lead with the report attached.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

GHL_BASE_URL = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"


def _headers() -> dict:
    """Build auth headers for GHL API calls."""
    api_key = os.environ.get("GHL_API_KEY")
    if not api_key:
        raise RuntimeError("GHL_API_KEY not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Version": GHL_API_VERSION,
    }


def upload_pdf(contact_id: str, pdf_path: str, filename: str) -> str:
    """Upload a PDF to GHL Conversations and return the hosted URL.

    Args:
        contact_id: GHL contact ID.
        pdf_path: Local path to the PDF file.
        filename: Display filename for the attachment.

    Returns:
        The hosted URL of the uploaded file.
    """
    url = f"{GHL_BASE_URL}/conversations/messages/upload"

    with open(pdf_path, "rb") as f:
        resp = requests.post(
            url,
            headers=_headers(),
            data={"contactId": contact_id},
            files={"fileAttachment": (filename, f, "application/pdf")},
            timeout=30,
        )

    resp.raise_for_status()
    data = resp.json()

    # Response can be {"uploadedFiles": {"filename": "url"}} (dict)
    # or {"urls": ["url1", ...]} (list) depending on API version.
    uploaded = data.get("uploadedFiles") or {}
    if isinstance(uploaded, dict) and uploaded:
        file_url = next(iter(uploaded.values()))
    elif isinstance(uploaded, list) and uploaded:
        file_url = uploaded[0] if isinstance(uploaded[0], str) else uploaded[0].get("url", "")
    else:
        urls = data.get("urls") or []
        if not urls:
            raise RuntimeError(f"GHL upload returned no file URLs: {data}")
        file_url = urls[0] if isinstance(urls[0], str) else urls[0].get("url", "")
    logger.info("PDF uploaded to GHL: %s", file_url)
    return file_url


def send_report_email(
    contact_id: str,
    email: str,
    contact_name: str,
    business_name: str,
    pdf_url: str,
    filename: str,
) -> None:
    """Send the competitor report email via GHL Conversations API.

    Args:
        contact_id: GHL contact ID.
        email: Lead's email address.
        contact_name: Lead's full name (used in greeting).
        business_name: The lead's business name.
        pdf_url: Hosted URL of the uploaded PDF.
        filename: Display filename for the attachment.
    """
    url = f"{GHL_BASE_URL}/conversations/messages"

    first_name = contact_name.split()[0] if contact_name.strip() else "there"

    html_body = f"""\
<p>Hi {first_name},</p>

<p>Thanks for requesting your Google Maps Competitor Report for <strong>{business_name}</strong>.</p>

<p>Your personalised report is attached to this email. It covers:</p>
<ul>
  <li>How your Google Business Profile stacks up against local competitors</li>
  <li>What the top-ranking businesses in your area are doing differently</li>
  <li>How many potential customers you could be missing out on each month</li>
  <li>Quick fixes to start showing up ahead of the competition</li>
</ul>

<p>Want us to walk you through it? <a href="https://go.plumbelecmarketing.com/schedule">Book a free 15-minute call</a> and we'll show you exactly what to focus on first.</p>

<p>Cheers,<br>
Tom Richards<br>
PlumbElec Marketing</p>
"""

    payload = {
        "type": "Email",
        "contactId": contact_id,
        "subject": f"Your Google Maps Competitor Report - {business_name}",
        "html": html_body,
        "attachments": [pdf_url],
    }

    headers = _headers()
    headers["Content-Type"] = "application/json"

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()

    logger.info("Report email sent to %s via GHL", email)
