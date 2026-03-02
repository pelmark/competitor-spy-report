"""
AI-powered content generation for the Competitor Spy Report.

Calls Claude Opus to generate structured JSON content for three report
sections: The Problem, What's This Costing You, and What Needs to Happen.
"""

import json
import logging
import os

from anthropic import Anthropic

from src.models import (
    AnalysisContent,
    Competitor,
    KeywordResult,
    ReportData,
    ScoreBreakdown,
)

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-6"
MAX_TOKENS = 2000


def _fallback_analysis() -> AnalysisContent:
    """Return generic content when Claude API is unavailable."""
    return AnalysisContent(
        score_explanation=(
            "This score measures how well your Google Business Profile is set up "
            "compared to the businesses that are actually showing up when people "
            "search for your services."
        ),
        pattern_interrupt=(
            "Your competitors are showing up ahead of you in local search results "
            "- even when your profile has more going for it on paper."
        ),
        competitors_doing_right=[
            "Several competitors in your area have optimised their profiles with "
            "the right categories, photos, and descriptions.",
            "The top-ranking businesses tend to have strong review counts and "
            "consistent information across their profiles.",
        ],
        falling_behind=[
            "Your profile has gaps in key areas that Google uses to decide who "
            "shows up first in Maps results.",
            "Competitors with fewer reviews are outranking you because their "
            "profiles are more complete in the areas Google cares about most.",
        ],
        search_framing=(
            "These aren't just numbers - they're real people in your area picking "
            "up the phone or jumping on Google to find someone right now."
        ),
        math_chain=(
            "If your business ranked in the top 3 on Google Maps, you'd be "
            "capturing a significant share of these searches every single month."
        ),
        provocative_close=(
            "What's your average job worth? Multiply that by the jobs you're "
            "missing out on. That's what this is costing you every month - not "
            "to mention the repeat work and referrals that would come from those jobs."
        ),
        action_items=[
            {
                "name": "Complete your profile",
                "explanation": (
                    "Key sections of your Google Business Profile are missing or "
                    "incomplete, which tells Google you're not a serious option."
                ),
            },
            {
                "name": "Close the review gap",
                "explanation": (
                    "Your competitors are building trust with potential customers "
                    "through consistent reviews. You need to match that momentum."
                ),
            },
            {
                "name": "Add more photos",
                "explanation": (
                    "Profiles with more photos get more clicks. Your competitors "
                    "are ahead of you here and it's an easy win."
                ),
            },
            {
                "name": "Fix your visibility gaps",
                "explanation": (
                    "You're not showing up where it matters most - the top of "
                    "Google Maps results for your key service areas."
                ),
            },
        ],
        closing_bridge=(
            "None of this is complicated - but it needs to be done right, "
            "and it needs to be done consistently."
        ),
    )


def _build_competitor_summary(competitors: list[Competitor]) -> str:
    """Format competitor data into a readable block for the prompt."""
    lines = []
    for c in competitors:
        if c.is_prospect:
            continue
        parts = [
            f"- {c.business_name}",
            f"  Rating: {c.star_rating} ({c.review_count} reviews)",
            f"  Photos: {c.photo_count}",
            f"  Category: {c.primary_category or 'Not set'}",
            f"  Website: {'Yes' if c.has_website else 'No'}",
            f"  Address: {c.address_type}",
            f"  Maps top 3: {'Yes' if c.maps_top_3 else 'No'}"
            + (f" (position {c.maps_position})" if c.maps_position else ""),
            f"  Organic top 10: {'Yes' if c.organic_top_10 else 'No'}",
            f"  Description: {'Yes' if c.has_description else 'No'}",
        ]
        if c.keyword_stuffed:
            parts.append("  ⚠ Keyword stuffing detected")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def _build_score_summary(score: ScoreBreakdown) -> str:
    """Format the prospect's score breakdown for the prompt."""
    return (
        f"Total: {score.total}/100 ({score.rating})\n"
        f"  Business Name Match: {score.business_name_match}/15 (Extreme priority)\n"
        f"  Website: {score.website}/12 (Extreme priority)\n"
        f"  Address Type: {score.address_type}/12 (Extreme priority)\n"
        f"  Primary Category: {score.primary_category}/12 (Extreme priority)\n"
        f"  Review Average: {score.review_average}/10 (High priority)\n"
        f"  Review Count: {score.review_count}/10 (High priority)\n"
        f"  Photos: {score.photos}/12 (High priority)\n"
        f"  Organic Top 10: {score.organic_top_10}/5 (High priority)\n"
        f"  Description: {score.description}/7 (Medium priority)"
    )


def _build_area_stats(result: KeywordResult) -> str:
    """Format area-level stats for the prompt."""
    return (
        f"Keyword: {result.keyword}\n"
        f"Location: {result.location} ({result.level})\n"
        f"Total competitors analysed: {result.total_competitors}\n"
        f"Median review count: {result.area_avg_reviews:.0f}\n"
        f"Average star rating: {result.area_avg_rating:.1f}\n"
        f"Median photo count: {result.area_avg_photos:.0f}\n"
        f"Competitors with website: {result.competitors_with_website}"
    )


def _build_prompt(
    report_data: ReportData,
    prospect_score: ScoreBreakdown,
    total_vol: int,
    potential_clicks: int,
    potential_leads: int,
    potential_jobs: int,
) -> str:
    """Assemble the full analysis prompt from report data."""
    lead = report_data.lead

    # Prospect's own data (if found in the results)
    prospect_info = "Not found in search results."
    for result in [report_data.suburb_result, report_data.lga_result]:
        if result.prospect:
            p = result.prospect
            prospect_info = (
                f"Business: {p.business_name}\n"
                f"Rating: {p.star_rating} ({p.review_count} reviews)\n"
                f"Photos: {p.photo_count}\n"
                f"Category: {p.primary_category or 'Not set'}\n"
                f"Website: {'Yes' if p.has_website else 'No'}\n"
                f"Address: {p.address_type}\n"
                f"Maps top 3: {'Yes' if p.maps_top_3 else 'No'}\n"
                f"Organic top 10: {'Yes' if p.organic_top_10 else 'No'}\n"
                f"Description: {'Yes' if p.has_description else 'No'}"
            )
            break

    # Keyword volume breakdown
    kv_lines = []
    for kv in report_data.keyword_volumes:
        kv_lines.append(f"  {kv.keyword}: {kv.search_volume}/mo")
    kv_text = "\n".join(kv_lines) if kv_lines else "  No keyword volume data available."

    return f"""You are a local SEO consultant writing content for a competitor analysis report. The report is for a trade business owner — a tradie, not a marketer. Write in plain English that a sparky with 3 trucks would understand at 6am.

The prospect is a {lead.trade_type} in {lead.suburb}, {lead.state}.

PROSPECT'S PROFILE:
{prospect_info}

PROSPECT'S GBP OPTIMISATION SCORE:
{_build_score_summary(prospect_score)}

SUBURB-LEVEL RESULTS:
{_build_area_stats(report_data.suburb_result)}

Competitors:
{_build_competitor_summary(report_data.suburb_result.competitors)}

LGA-LEVEL RESULTS:
{_build_area_stats(report_data.lga_result)}

Competitors:
{_build_competitor_summary(report_data.lga_result.competitors)}

SEARCH VOLUME DATA:
Total monthly searches: {total_vol:,}
{kv_text}
Calculated conversion chain: {total_vol:,} searches → {potential_clicks:,} land on top 3 profiles → {potential_leads:,} enquiries → {potential_jobs:,} paying jobs

Write content for THREE sections of the report. Return your response as valid JSON matching this exact structure:

{{
  "score_explanation": "One sentence that references their actual score (e.g. 'Your profile scored 69 out of 100...') and explains what it means in plain English. Do NOT just say 'this score measures...' - tell them their specific result and what it tells them about their position.",

  "pattern_interrupt": "2-3 sentences MAX that use their actual data to create a wake-up moment. Use their review count, photo count, or other specific numbers as the hook. Make them feel the gap between their effort and their visibility. Example tone: 'You've built up 639 reviews — more than every competitor combined — but when someone searches electrician Neutral Bay, you're nowhere to be found.'",

  "competitors_doing_right": [
    "Bullet 1 — what a specific named competitor is doing well, with actual numbers. Max 25 words.",
    "Bullet 2 — a DIFFERENT specific insight about a DIFFERENT competitor. Max 25 words."
  ],

  "falling_behind": [
    "Bullet 1 — a specific gap the prospect has. Instead of 'SAB listing' say 'service area listing without a street address shown'. Max 25 words.",
    "Bullet 2 — a COMPLETELY DIFFERENT gap from bullet 1 AND from the pattern interrupt. Do NOT repeat the same point about not ranking or not showing up — find a different weakness (e.g. missing organic presence, photo ratio vs competitors, profile completeness). Max 25 words."
  ],

  "search_framing": "2-3 sentences framing the {total_vol:,} monthly searches as real people actively looking to hire RIGHT NOW. These aren't impressions or clicks — they're homeowners picking up the phone. Make it visceral.",

  "math_chain": "Break down the conversion chain in a way a tradie can follow in 5 seconds: {total_vol:,} searches/month → {potential_clicks:,} land on the top 3 profiles → {potential_leads:,} enquiries → {potential_jobs:,} paying jobs. Write it as a flowing sentence or two, not a formula.",

  "provocative_close": "One punchy line that makes THEM calculate the dollar value. Don't put a dollar figure in — make them do the maths. Must end with a line about repeat work / referrals they'd also get. Example: 'What's your average job worth? Multiply that by {potential_jobs:,}. That's what you're leaving on the table every single month — not to mention the repeat work and referrals that would come from those jobs.'",

  "action_items": [
    {{"name": "Bold name 3-5 words", "explanation": "1-2 sentences. Reference specific competitor names and data from the results. Explain the IMPACT on their business in plain English — NOT internal scoring methodology. Bad: 'You scored 0 out of 15 on business name match'. Good: 'Captain Cook has 339 reviews and ranks #1 because their profile ticks every box Google looks for — yours has gaps that are pushing you down'. Be specific enough to build trust but don't give step-by-step instructions."}},
    {{"name": "...", "explanation": "..."}},
    {{"name": "...", "explanation": "..."}},
    {{"name": "...", "explanation": "..."}}
  ],

  "closing_bridge": "A single sentence that bridges from the action items to the CTA page. Frame these as facts from the data, not opinions. Nudge them toward taking action."
}}

RULES:
- Be direct. No filler phrases like "in today's competitive landscape" or "it's worth noting".
- Use plain language a tradie would understand at 6am. No jargon like "ranking signals", "profile configuration", "optimisation". Say what you mean in everyday words.
- Phrases like "proper optimisation" or "right configuration" are too vague — say specifically what needs to change (e.g. "your photos, description, and services sections").
- Reference specific competitor names and numbers from the data.
- NEVER recommend changing the business name. Business name match is a scoring factor only — it is what it is.
- NEVER recommend changing the business address or address type.
- NEVER reference internal scoring numbers (e.g. "scored 0/15 on business name match"). The prospect doesn't know the scoring system — talk about outcomes and visibility, not scores.
- Do NOT mention AI Overviews or AI search in any way.
- NEVER use em dashes (—). Use a regular hyphen-dash (-) instead.
- STRICT WORD LIMITS — content WILL overflow the page if you exceed these:
  - Page 2 (score_explanation + pattern_interrupt + all bullets): MAXIMUM 150 words. Keep bullets to 2 per section, max 25 words each.
  - Page 4 (search_framing + math_chain + provocative_close): MAXIMUM 120 words.
  - Page 5 (4 action items + closing_bridge): MAXIMUM 150 words. Each action item explanation max 2 sentences.
- Each action item "name" must be exactly 3-5 words.
- Every sentence should make them feel the cost of doing nothing.
- Each bullet/action item must make a DISTINCT point — never repeat the same insight.
- Return ONLY the JSON object. No markdown code fences. No preamble. No explanation."""


def _parse_response(raw: str) -> AnalysisContent:
    """Parse Claude's JSON response into an AnalysisContent object."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    data = json.loads(text)

    # Strip em dashes from all string values
    for key, val in data.items():
        if isinstance(val, str):
            data[key] = val.replace("—", "-")
        elif isinstance(val, list):
            cleaned = []
            for item in val:
                if isinstance(item, str):
                    cleaned.append(item.replace("—", "-"))
                elif isinstance(item, dict):
                    cleaned.append({k: v.replace("—", "-") if isinstance(v, str) else v for k, v in item.items()})
                else:
                    cleaned.append(item)
            data[key] = cleaned

    return AnalysisContent(
        score_explanation=data.get("score_explanation", ""),
        pattern_interrupt=data.get("pattern_interrupt", ""),
        competitors_doing_right=data.get("competitors_doing_right", []),
        falling_behind=data.get("falling_behind", []),
        search_framing=data.get("search_framing", ""),
        math_chain=data.get("math_chain", ""),
        provocative_close=data.get("provocative_close", ""),
        action_items=data.get("action_items", []),
        closing_bridge=data.get("closing_bridge", ""),
    )


def generate_analysis(
    report_data: ReportData,
    prospect_score: ScoreBreakdown,
    total_vol: int = 0,
    potential_clicks: int = 0,
    potential_leads: int = 0,
    potential_jobs: int = 0,
) -> AnalysisContent:
    """Generate structured AI content for three report sections.

    Args:
        report_data: Full report data including lead info and keyword results.
        prospect_score: The prospect's scored GBP breakdown.
        total_vol: Total monthly search volume across all keywords.
        potential_clicks: Estimated clicks if ranking top 3 (35% CTR).
        potential_leads: Estimated enquiries (20% conversion).
        potential_jobs: Estimated jobs (50% close rate).

    Returns:
        AnalysisContent with structured content for pages 2, 4, and 5.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set — returning fallback analysis")
        return _fallback_analysis()

    prompt = _build_prompt(
        report_data, prospect_score,
        total_vol, potential_clicks, potential_leads, potential_jobs,
    )

    try:
        client = Anthropic(api_key=api_key)

        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )

        raw = message.content[0].text
        logger.info(
            "Analysis generated: %d chars, %d input tokens, %d output tokens",
            len(raw),
            message.usage.input_tokens,
            message.usage.output_tokens,
        )

        return _parse_response(raw)

    except json.JSONDecodeError:
        logger.exception("Failed to parse analysis JSON — returning fallback")
        return _fallback_analysis()
    except Exception:
        logger.exception("Failed to generate analysis via Claude API")
        return _fallback_analysis()
