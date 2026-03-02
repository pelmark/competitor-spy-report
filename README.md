# Competitor Spy Report

Lead magnet tool for PlumbElec Marketing. Takes a trade business's details, pulls real competitor data from Google via DataForSEO, scores their Google Business Profile, generates an AI-written analysis, and outputs a branded 7-page PDF report. Optionally emails the report to the lead via Go High Level.

## Architecture

```
                        POST /generate-report
                               │
                               ▼
                         ┌──────────┐
                         │  main.py │  Flask app — validates input, orchestrates pipeline
                         └────┬─────┘
                              │
               ┌──────────────┼──────────────────┐
               ▼              ▼                   ▼
        ┌─────────────┐ ┌──────────┐     ┌────────────┐
        │dataforseo.py│ │scoring.py│     │analysis.py │
        │             │ │          │     │            │
        │ Maps SERP   │ │ 9-factor │     │ Claude AI  │
        │ Organic SERP│ │ scoring  │     │ analysis   │
        │ Place Detail│ │ engine   │     │ writer     │
        │ Keyword Vol │ │ (100 pts)│     │            │
        └──────┬──────┘ └──────────┘     └────────────┘
               │                                │
               │         ┌──────────┐           │
               └────────►│ report.py├◄──────────┘
                         │          │
                         │WeasyPrint│
                         │ PDF gen  │
                         └────┬─────┘
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
               Return PDF       Upload + email
               (no contact_id)  via GHL (ghl.py)
```

## Project Structure

```
competitor-spy-report/
├── main.py                 # Flask entry point, pipeline orchestration
├── src/
│   ├── models.py           # All data classes (LeadInput, Competitor, ScoreBreakdown, etc.)
│   ├── dataforseo.py       # DataForSEO API client (Maps, Organic, Place Details, Keyword Volume)
│   ├── scoring.py          # GBP optimisation scoring engine (9 factors, 100 pts)
│   ├── analysis.py         # Claude AI analysis generation
│   ├── report.py           # WeasyPrint PDF generator (Jinja2 + CSS)
│   └── ghl.py              # Go High Level API client (PDF upload + email delivery)
├── templates/
│   └── report.html.j2      # Jinja2 HTML template for the 7-page report
├── static/
│   ├── styles.css          # WeasyPrint stylesheet (landscape A4, brand fonts/colours)
│   ├── logo.png            # PlumbElec Marketing logo
│   ├── phone-mockup.png    # Cover page illustration
│   ├── headshot.png        # CTA page headshot (optional)
│   ├── client-logos.png    # CTA page client logos (optional)
│   └── fonts/              # Syne-SemiBold.woff2, Inter-Light.woff2
├── assets/
│   └── logo.png            # Brand logo (legacy location)
├── output/                 # Generated PDFs (auto-cleaned after 24 hours)
├── test_render.py          # Renders a test PDF with mock data (no API calls)
├── .env                    # API credentials (git-ignored)
├── .env.example            # Template for required environment variables
├── requirements.txt        # Python dependencies
├── Dockerfile              # Production container
└── railway.json            # Railway deployment config
```

## Report Pages (7 pages, landscape A4)

| Page | Title | Content |
|------|-------|---------|
| **1** | Cover | PlumbElec branding, business name, suburb, phone mockup illustration |
| **2** | The Problem | Score out of 100 with rating tier, AI-written score explanation, pattern interrupt, "What your competitors are doing right" + "Where you're falling behind" bullets |
| **3** | Your Profile vs Your Competitors | Suburb-level competitor table + LGA-level competitor table. 10 columns: name, Maps top 3, organic top 10, website, address type, category, stars, reviews, photos, description |
| **4** | What's This Costing You | Total monthly search volume, keyword breakdown, conversion chain (searches -> clicks -> leads -> jobs), provocative dollar-value close |
| **5** | Some Quick Fixes | 4 AI-generated action items with specific competitor references and data |
| **6** | Google Maps Best Practices | Two-column checklist: Profile Setup, Reviews, Weekly Activity, Citations & Consistency, Growth |
| **7** | CTA | Headshot, "Book a free 15-minute call", booking link, testimonials link, client logos |

**Brand specs:** Teal `#0CC3C9`, Black `#000000`, Syne SemiBold headings, Inter Light body text.

## Data Pipeline

### Step 1: DataForSEO API Calls (`dataforseo.py`)

For each keyword level (suburb + LGA), the pipeline makes these API calls:

| # | Endpoint | Purpose | Cost |
|---|----------|---------|------|
| 1 | `/serp/google/maps/live/advanced` | Google Maps SERP — positions, ratings, reviews, photos, place IDs | ~$0.004 |
| 2 | `/serp/google/organic/live/advanced` | Google Organic SERP — website rankings, organic positions | ~$0.004 |
| 3 | `/business_data/google/my_business_info/live` | Place Details — enriches each competitor with photos, description, services, category, address type | ~$0.002 each |
| 4 | `/keywords_data/google_ads/search_volume/live` | Keyword volume — monthly search volume for 4 keywords in one call | ~$0.075 |

**Keyword construction:**
- Suburb: `{trade_type} {suburb}` (e.g. "plumber Marrickville")
- LGA: `{trade_type} {lga}` (e.g. "plumber Inner West")
- Emergency suburb: `emergency {trade_type} {suburb}`
- Emergency LGA: `emergency {trade_type} {lga}`

**Place Details enrichment** runs for up to 10 competitors per keyword (controlled by `MAX_PLACE_DETAIL_LOOKUPS`). The prospect is always enriched first regardless of position.

**Prospect matching** uses fuzzy name matching (`_is_prospect_match`): case-insensitive partial matching where either name contains the other, or all words from the shorter name appear in the longer one.

### Step 2: Scoring (`scoring.py`)

9 factors, 100 points maximum. Scores the prospect's GBP against area medians.

| # | Factor | Max | Priority | Logic |
|---|--------|-----|----------|-------|
| 1 | Business Name Match | 15 | Extreme | 15 = all keyword terms in name, 8 = partial match, 0 = none |
| 2 | Website | 12 | Extreme | 12 = has website, 0 = none |
| 3 | Address Type | 12 | Extreme | 12 = physical, 6 = SAB (service area business), 0 = unknown |
| 4 | Primary Category | 12 | Extreme | 12 = optimal GBP category for trade, 6 = related category, 0 = wrong |
| 5 | Review Average | 10 | High | 10 = 4.5+ stars, 6 = 4.0+, 2 = below 4.0 |
| 6 | Review Count | 10 | High | 10 = at or above area median, 3 = below |
| 7 | Photos | 12 | High | 12 = at or above area median, 3 = below |
| 8 | Organic Top 10 | 5 | High | 5 = appears in organic top 10, 0 = doesn't |
| 9 | Description | 7 | Medium | 7 = has GBP description, 0 = none |

**Rating tiers:** Excellent (80+), Good (60-79), Average (40-59), Weak (20-39), Poor (0-19)

**Category mapping** (`CATEGORY_MAP`): maps trade types (plumber, electrician, hvac, roofer, landscaper, painter, carpenter) to optimal and related GBP categories. Unknown trades fall back to string matching.

**Keyword stuffing detection**: flags business names with 3+ spam/keyword terms. Detected names get an asterisk in the competitor table and a footnote. The AI analysis is instructed to never recommend changing business names.

### Step 3: AI Analysis (`analysis.py`)

Calls Claude (claude-opus-4-6, max 2000 tokens) with a structured prompt containing:
- Prospect's profile data and score breakdown
- Suburb and LGA area stats (median reviews, avg rating, median photos)
- Full competitor data for both levels
- Search volume and pre-computed conversion chain

The prompt requests a JSON response with 9 content sections used across pages 2, 4, and 5:

| Field | Used On | Description |
|-------|---------|-------------|
| `score_explanation` | Page 2 | One sentence referencing actual score and position |
| `pattern_interrupt` | Page 2 | 2-3 sentences using real data to create a wake-up moment |
| `competitors_doing_right` | Page 2 | 2 bullets with specific competitor names + numbers |
| `falling_behind` | Page 2 | 2 bullets on prospect's specific gaps |
| `search_framing` | Page 4 | Makes search volume feel like real people hiring NOW |
| `math_chain` | Page 4 | Conversion flow as prose: searches -> clicks -> leads -> jobs |
| `provocative_close` | Page 4 | Makes the prospect calculate their own dollar loss |
| `action_items` | Page 5 | 4 items with name (3-5 words) + explanation (1-2 sentences) |
| `closing_bridge` | Page 5 | Single sentence bridging to CTA |

**Prompt guardrails:**
- Never recommend changing business name or address
- Never mention AI Overviews or AI search
- Never use em dashes (safety net strips them from Claude's response)
- Strict word limits per page to prevent PDF overflow
- Plain language a tradie understands at 6am, no marketing jargon

Falls back to generic content if the API key is missing or the call fails.

### Step 4: PDF Generation (`report.py`)

Uses WeasyPrint to render a Jinja2 HTML template (`templates/report.html.j2`) with CSS (`static/styles.css`) into a landscape A4 PDF.

Process:
1. Loads Jinja2 template and builds context dict from ReportData
2. Renders HTML string with all data
3. Applies CSS stylesheet with embedded web fonts (Syne, Inter)
4. WeasyPrint converts to PDF with `base_url` pointing to `static/` for image resolution
5. Writes PDF to `output/` directory

### Step 5: Delivery (optional GHL integration)

If `contact_id` is included in the request payload, the report is emailed to the lead via Go High Level's Conversations API. If no `contact_id`, the PDF is returned directly as a file download.

**GHL flow:**
1. Upload PDF to GHL via `POST /conversations/messages/upload` (multipart form)
2. GHL returns a hosted URL on their CDN (`static-assets.internal.usercontent.site`)
3. Send email via `POST /conversations/messages` with the PDF URL in the `attachments` array
4. Email appears in the GHL conversation thread for the contact

See the [GHL Integration](#ghl-integration-ghlpy) section below for full details.

## GHL Integration (`ghl.py`)

### Overview

The Go High Level integration enables automatic email delivery of reports to leads. This is designed for the workflow: **Facebook Lead Ad -> GHL Workflow -> Report API -> email with PDF attached**.

### How It Works

```
FB Lead Ad form submitted
        │
        ▼
GHL captures contact (with custom fields: trade_type, suburb, lga)
        │
        ▼
GHL Workflow triggers Outbound Webhook
  POST https://competitor-spy-report-production.up.railway.app/generate-report
  Body: { contact_id, trade_type, business_name, suburb, lga, ... }
        │
        ▼
Report API generates PDF (DataForSEO -> Scoring -> Claude -> WeasyPrint)
        │
        ▼
Upload PDF to GHL Conversations (multipart form upload)
  → Returns hosted PDF URL
        │
        ▼
Send email via GHL Conversations API
  → Email appears in contact's conversation thread
  → Lead receives email with PDF attached
        │
        ▼
API returns { "status": "ok", "message": "Report emailed to lead" }
```

### Dual Mode

| Scenario | Behaviour |
|----------|-----------|
| `contact_id` present in payload | Uploads PDF to GHL, sends email, returns JSON `{"status": "ok"}` |
| `contact_id` absent | Returns the PDF file directly as a download (for manual testing) |

### GHL API Details

| Setting | Value |
|---------|-------|
| Base URL | `https://services.leadconnectorhq.com` |
| API Version Header | `2021-07-28` |
| Auth | `Authorization: Bearer {GHL_API_KEY}` (Private Integration Token) |

**Upload endpoint:** `POST /conversations/messages/upload`
- Multipart form with `contactId` + `fileAttachment` (PDF binary)
- Response format: `{"uploadedFiles": {"filename.pdf": "https://hosted-url..."}}`
- The PDF is stored on GHL's CDN and persists with the conversation

**Send endpoint:** `POST /conversations/messages`
- JSON body with `type: "Email"`, `contactId`, `subject`, `html`, `attachments: ["url"]`
- Attachments must be a plain string array (not `[{"url": "..."}]`)
- Response: `{"msg": "Email queued successfully."}`

### GHL Setup Requirements

**1. Private Integration App** (GHL Settings -> Integrations -> Private Integrations):

Required scopes:
- `conversations.write` — create conversations
- `conversations/message.write` — send messages
- `conversations/message.readonly` — view messages
- `contacts.readonly` — read contact data
- `medias.write` — upload files

Copy the API key (starts with `pit-`) -> add to `.env` as `GHL_API_KEY`.

**2. Location ID:**

Find in GHL Settings -> Business Info, or from the URL: `app.gohighlevel.com/v2/location/{LOCATION_ID}/...`

Add to `.env` as `GHL_LOCATION_ID`.

**3. GHL Workflow** (for automated delivery):

- **Trigger:** Facebook Lead Ad form submission
- **Action:** Custom Webhook (POST)
- **URL:** `https://competitor-spy-report-production.up.railway.app/generate-report`
- **Headers:** `Authorization: Bearer {WEBHOOK_SECRET}`, `Content-Type: application/json`
- **Body mapping:**

```json
{
  "contact_id": "{{contact.id}}",
  "trade_type": "{{contact.custom_field.trade_type}}",
  "business_name": "{{contact.company_name}}",
  "contact_name": "{{contact.first_name}} {{contact.last_name}}",
  "email": "{{contact.email}}",
  "phone": "{{contact.phone}}",
  "suburb": "{{contact.custom_field.suburb}}",
  "lga": "{{contact.custom_field.lga}}",
  "state": "{{contact.custom_field.state}}",
  "website_url": "{{contact.website}}"
}
```

Custom fields (`trade_type`, `suburb`, `lga`, `state`) must exist in GHL and be captured on the FB Lead Ad form.

### Email Template

The email sent to leads includes:
- Greeting using first name
- Brief description of what the report covers (4 bullet points)
- CTA link to book a 15-minute strategy call
- Signed as Tom Richards / PlumbElec Marketing
- PDF attached via the uploaded URL

## Input Format

`POST /generate-report` accepts JSON:

```json
{
  "trade_type": "plumber",
  "business_name": "Plumbwell Plumbing Services",
  "contact_name": "Tom Richards",
  "email": "info@plumbelecmarketing.com",
  "phone": "+61400000001",
  "suburb": "Marrickville",
  "lga": "Inner West",
  "state": "NSW",
  "website_url": "https://plumbwellplumbers.com.au/",
  "contact_id": "fR76ftQf5EL3URf0QVPu"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `trade_type` | Yes | Lowercase trade name: plumber, electrician, hvac, roofer, landscaper, painter, carpenter |
| `business_name` | Yes | Used for prospect matching in search results |
| `contact_name` | Yes | Used in email greeting (first name extracted) |
| `email` | Yes | Used for GHL email delivery |
| `phone` | Yes | Stored for CRM |
| `suburb` | Yes | Used to construct suburb-level keyword |
| `lga` | Yes | Used to construct LGA-level keyword |
| `state` | No | Defaults to "NSW" |
| `website_url` | No | `null` or omit if no website |
| `contact_id` | No | GHL contact ID — if provided, emails report via GHL instead of returning PDF |

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Dependencies:
- `flask>=3.0` — web framework
- `gunicorn>=22.0` — production WSGI server
- `requests>=2.31` — HTTP client for DataForSEO and GHL
- `weasyprint>=62.0` — HTML/CSS to PDF conversion
- `jinja2>=3.1` — template engine
- `anthropic>=0.40.0` — Claude API client
- `python-dotenv>=1.0` — .env file loading

**WeasyPrint system dependencies** (macOS):
```bash
brew install pango libffi
```

When running locally on macOS, you may need:
```bash
export DYLD_LIBRARY_PATH=/opt/homebrew/lib
```

### 2. Configure environment

```bash
cp .env.example .env
```

| Variable | Required | Source |
|----------|----------|--------|
| `DATAFORSEO_LOGIN` | Yes | DataForSEO Dashboard -> API Access (your email) |
| `DATAFORSEO_PASSWORD` | Yes | DataForSEO Dashboard -> API Access (API password, not account password) |
| `ANTHROPIC_API_KEY` | Yes | https://console.anthropic.com |
| `GHL_API_KEY` | For email delivery | GHL Settings -> Private Integrations (starts with `pit-`) |
| `GHL_LOCATION_ID` | For email delivery | GHL Settings -> Business Info or URL |
| `BOOKING_URL` | No | CTA booking link (defaults to PlumbElec schedule page) |
| `WEBHOOK_SECRET` | No | Bearer token for endpoint auth — leave empty for open access |

### 3. Run locally

```bash
python main.py
```

Starts Flask on port 5000 (or `$PORT` env var). Set `FLASK_DEBUG=1` for debug mode.

Note: port 5000 may conflict with macOS AirPlay Receiver. Use `PORT=5050 python main.py` as an alternative.

### 4. Generate a report (returns PDF)

```bash
curl -X POST http://localhost:5000/generate-report \
  -H "Content-Type: application/json" \
  -d '{
    "trade_type": "plumber",
    "business_name": "Plumbwell Plumbing Services",
    "contact_name": "Tom Richards",
    "email": "info@plumbelecmarketing.com",
    "phone": "+61400000001",
    "suburb": "Marrickville",
    "lga": "Inner West",
    "state": "NSW"
  }' \
  --output report.pdf
```

### 5. Generate a report (emails via GHL)

```bash
curl -X POST http://localhost:5000/generate-report \
  -H "Content-Type: application/json" \
  -d '{
    "contact_id": "fR76ftQf5EL3URf0QVPu",
    "trade_type": "plumber",
    "business_name": "Plumbwell Plumbing Services",
    "contact_name": "Tom Richards",
    "email": "info@plumbelecmarketing.com",
    "phone": "+61400000001",
    "suburb": "Marrickville",
    "lga": "Inner West",
    "state": "NSW"
  }'
# → {"status": "ok", "message": "Report emailed to lead"}
```

### 6. Health check

```bash
curl http://localhost:5000/health
# → {"status": "ok"}
```

### 7. Test PDF rendering (no API calls)

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib python test_render.py
```

Renders a PDF with hardcoded mock data to `output/`. Useful for testing template and styling changes without API costs.

## Deployment (Railway)

**Production URL:** `https://competitor-spy-report-production.up.railway.app`

The app is deployed on Railway from the `pelmark/competitor-spy-report` GitHub repo.

1. Push to `main` — Railway auto-deploys
2. Environment variables are configured in the Railway dashboard
3. Railway builds from the Dockerfile

The `railway.json` configures:
- Dockerfile-based build
- Auto-restart on failure (max 10 retries)

The Dockerfile runs: `gunicorn --bind 0.0.0.0:$PORT --timeout 120 main:app`

The `--timeout 120` is important — a full report pipeline takes 30-90 seconds due to sequential DataForSEO API calls with rate-limiting delays.

## Cost Per Report

| API Call | Cost |
|----------|------|
| DataForSEO Maps SERP (x2 keywords) | ~$0.008 |
| DataForSEO Organic SERP (x2 keywords) | ~$0.008 |
| DataForSEO Place Details (up to 20 lookups) | ~$0.04 |
| DataForSEO Keyword Volume (1 call, 4 keywords) | ~$0.075 |
| Claude Opus (analysis, ~2000 tokens) | ~$0.02-0.05 |
| **Total** | **~$0.15-0.18** |

## Key Design Decisions

- **Landscape A4 for everything**: the whole report is landscape to fit wide competitor tables. Portrait content like the cover uses generous margins and centred layout.
- **WeasyPrint over ReportLab**: switched from ReportLab to WeasyPrint (HTML/CSS to PDF) for easier styling, web fonts, and template-driven layout. Uses Jinja2 for templating.
- **Table-based columns in WeasyPrint**: CSS floats don't reliably render across page breaks in WeasyPrint. The best practices page uses an HTML `<table>` for its two-column layout.
- **Sequential API calls with delays**: DataForSEO rate limits are generous but 0.5s delays between calls add safety. Place Details are the bottleneck — up to 10 lookups per keyword x 2 keywords.
- **Prospect always enriched first**: even if the prospect is ranked 20th in Maps, their Place Details are fetched before any other competitor.
- **Fuzzy name matching over exact**: business names in Maps results don't always match exactly (e.g. "Plumbwell" vs "Plumbwell Plumbing Services"). The matcher handles partial matches and word-overlap.
- **Scoring uses area medians, not averages**: review count and photo count are compared against the median of the area's competitors, making the score robust to outliers.
- **AI analysis guardrails**: the prompt explicitly prohibits recommending business name changes, address changes, or mentioning AI Overviews. Em dashes are stripped from Claude's output as a safety net.
- **Fallback analysis**: if Claude API fails or the key isn't set, a generic fallback message is used rather than failing the entire report.
- **Dual delivery mode**: if `contact_id` is in the payload, emails via GHL. Otherwise returns the raw PDF. This keeps manual testing simple while supporting automated workflows.
- **24-hour PDF cleanup**: old PDFs in the output directory are automatically cleaned up on each request to prevent disk filling on the Railway deployment.

## File-by-File Reference

### `main.py`
Flask app with two routes: `GET /health` and `POST /generate-report`. Orchestrates the full pipeline: validate input -> DataForSEO -> scoring -> AI analysis -> PDF -> optional GHL delivery. Handles auth via optional `WEBHOOK_SECRET` Bearer token. Auto-cleans PDFs older than 24 hours.

### `src/models.py`
All dataclasses:
- `LeadInput` — input from the lead form
- `Competitor` — a single business's GBP data (rankings, ratings, reviews, photos, etc.)
- `ScoreBreakdown` — individual scores for 9 factors with `total` and `rating` properties
- `KeywordResult` — results for a single keyword search with computed area medians
- `KeywordVolume` — search volume for a single keyword
- `AnalysisContent` — structured AI-generated content (9 fields for pages 2, 4, and 5)
- `ReportData` — top-level container with suburb/LGA results, score, analysis, and keyword volumes

### `src/dataforseo.py`
DataForSEO API client. Key functions:
- `search_maps()` — Maps SERP search
- `search_organic()` — Organic SERP search
- `get_place_details()` — GBP enrichment via My Business Info endpoint
- `get_keyword_volumes()` — Google Ads search volume for multiple keywords in one call
- `search_keyword()` — orchestrates Maps + Organic + Place Details for a single keyword
- `generate_report_data()` — top-level function that runs both keyword levels + fetches volumes

### `src/scoring.py`
GBP scoring engine. Key functions:
- `score_competitor()` — scores a single Competitor across all 9 factors
- `check_business_name_match()` — keyword presence in business name (15/8/0)
- `check_primary_category()` — category matching via `CATEGORY_MAP` (12/6/0)
- `detect_keyword_stuffing()` — flags spam names

### `src/analysis.py`
Claude AI integration. Builds a structured prompt from report data and calls Claude Opus 4.6. Returns AnalysisContent with 9 structured fields. Strips em dashes from Claude's output. Falls back gracefully on API failure.

### `src/report.py`
WeasyPrint PDF generator. Renders Jinja2 HTML template with CSS into landscape A4 PDF. Key functions:
- `generate_pdf()` — public entry point
- `_prepare_context()` — builds template context dict from ReportData

### `src/ghl.py`
Go High Level API client. Key functions:
- `upload_pdf()` — uploads PDF to GHL Conversations, returns hosted URL
- `send_report_email()` — sends HTML email with PDF attached via GHL Conversations API

### `templates/report.html.j2`
Jinja2 HTML template for the 7-page PDF. Each `<section class="page">` maps to one printed page. Uses conditional blocks for optional assets (phone mockup, headshot, client logos).

### `static/styles.css`
WeasyPrint stylesheet. Landscape A4 `@page` rules, brand fonts via `@font-face`, page-specific layouts, competitor table styling, score badge, CTA page design.

### `test_render.py`
Standalone script that renders a PDF with hardcoded mock data (no API calls needed). Useful for testing template and styling changes.
