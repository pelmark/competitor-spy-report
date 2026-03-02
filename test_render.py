"""
Test script - renders a PDF with mock data (no API calls).
Run: python test_render.py
"""

import sys
sys.path.insert(0, ".")

from src.models import (
    AnalysisContent,
    Competitor,
    KeywordResult,
    KeywordVolume,
    LeadInput,
    ReportData,
    ScoreBreakdown,
)
from src.report import generate_pdf


def main():
    lead = LeadInput(
        trade_type="electrician",
        business_name="AB Electrical & Communications",
        contact_name="Andrew Brown",
        email="andrew@abelectrical.com.au",
        phone="0412 345 678",
        suburb="Neutral Bay",
        lga="North Sydney",
        state="NSW",
        website_url="https://abelectrical.com.au",
    )

    # --- Prospect ---
    prospect = Competitor(
        business_name="AB Electrical & Communications",
        maps_top_3=False,
        maps_position=None,
        organic_top_10=False,
        organic_position=None,
        website="https://abelectrical.com.au",
        has_website=True,
        address_type="sab",
        primary_category="Electrician",
        star_rating=5.0,
        review_count=639,
        photo_count=201,
        has_description=True,
        is_prospect=True,
    )

    # --- Suburb competitors ---
    suburb_competitors = [
        prospect,
        Competitor(
            business_name="A A BARCLAY ELECTRICAL",
            maps_top_3=True,
            maps_position=2,
            organic_top_10=False,
            has_website=True,
            address_type="physical",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=13,
            photo_count=75,
            has_description=False,
        ),
        Competitor(
            business_name="Captain Cook Electrical Sydney",
            maps_top_3=True,
            maps_position=1,
            organic_top_10=False,
            has_website=True,
            address_type="sab",
            primary_category="Electrician",
            star_rating=4.9,
            review_count=339,
            photo_count=18,
            has_description=True,
        ),
        Competitor(
            business_name="Montgomery Electrical",
            maps_top_3=True,
            maps_position=3,
            organic_top_10=True,
            has_website=True,
            address_type="sab",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=91,
            photo_count=13,
            has_description=True,
        ),
        Competitor(
            business_name="Kendo Electrical",
            maps_top_3=False,
            organic_top_10=False,
            has_website=False,
            address_type="physical",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=31,
            photo_count=59,
            has_description=True,
        ),
        Competitor(
            business_name="Innovative Comms & Electrical",
            maps_top_3=False,
            organic_top_10=True,
            has_website=True,
            address_type="physical",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=15,
            photo_count=6,
            has_description=True,
        ),
    ]

    suburb_result = KeywordResult(
        keyword="electrician Neutral Bay",
        location="Neutral Bay",
        level="suburb",
        competitors=suburb_competitors,
        prospect=prospect,
    )

    # --- LGA competitors (reuse some) ---
    lga_competitors = [
        prospect,
        Competitor(
            business_name="A A BARCLAY ELECTRICAL",
            maps_top_3=True,
            maps_position=1,
            organic_top_10=False,
            has_website=True,
            address_type="physical",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=13,
            photo_count=75,
            has_description=False,
        ),
        Competitor(
            business_name="Captain Cook Electrical Sydney",
            maps_top_3=True,
            maps_position=2,
            organic_top_10=False,
            has_website=True,
            address_type="sab",
            primary_category="Electrician",
            star_rating=4.9,
            review_count=339,
            photo_count=18,
            has_description=True,
        ),
        Competitor(
            business_name="Montgomery Electrical",
            maps_top_3=True,
            maps_position=3,
            organic_top_10=True,
            has_website=True,
            address_type="sab",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=91,
            photo_count=13,
            has_description=True,
        ),
        Competitor(
            business_name="Kendo Electrical",
            maps_top_3=False,
            organic_top_10=False,
            has_website=False,
            address_type="physical",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=31,
            photo_count=59,
            has_description=True,
        ),
        Competitor(
            business_name="Innovative Comms & Electrical",
            maps_top_3=False,
            organic_top_10=True,
            has_website=True,
            address_type="physical",
            primary_category="Electrician",
            star_rating=5.0,
            review_count=15,
            photo_count=6,
            has_description=True,
        ),
    ]

    lga_result = KeywordResult(
        keyword="electrician North Sydney",
        location="North Sydney",
        level="lga",
        competitors=lga_competitors,
        prospect=prospect,
    )

    # --- Score ---
    score = ScoreBreakdown(
        business_name_match=0,
        website=12,
        address_type=6,
        primary_category=12,
        review_average=10,
        review_count=10,
        photos=12,
        organic_top_10=0,
        description=7,
    )

    # --- Mock AI analysis ---
    analysis = AnalysisContent(
        score_explanation=(
            "This score measures how well your Google Business Profile stacks up "
            "against the competitors who are actually showing up when locals search "
            "for an electrician in your area."
        ),
        pattern_interrupt=(
            "You've built up 639 reviews and 201 photos - more than every competitor "
            "in Neutral Bay combined. But when someone searches 'electrician Neutral Bay', "
            "you're nowhere in the top 3 on Maps. Businesses with 13 reviews are showing "
            "up ahead of you."
        ),
        competitors_doing_right=[
            "A A Barclay Electrical has just 13 reviews but ranks #2 in Maps - they "
            "have a physical street address listed, which Google rewards with better "
            "local visibility.",
            "Captain Cook Electrical Sydney (339 reviews, position #1) has their "
            "category set correctly and a complete profile description.",
            "Montgomery Electrical shows up in both Maps top 3 AND organic top 10 - "
            "the only competitor doing both.",
        ],
        falling_behind=[
            "Your listing uses a service area without showing a street address - this "
            "means Google sees you as less 'local' than competitors with a shopfront or "
            "visible address, even though you have 639 reviews vs their 13.",
            "You're not ranking in organic search results at all. Montgomery and "
            "Innovative Comms both appear in organic top 10, giving them double the "
            "visibility.",
            "Despite having the best review count and photos in the area, your profile "
            "isn't converting that effort into Maps visibility.",
        ],
        search_framing=(
            "Every month, 440 people in your area type something like 'electrician "
            "Neutral Bay' into Google. These aren't tyre-kickers - they're homeowners "
            "with a flickering light or a tripped safety switch, ready to call the first "
            "sparky they see."
        ),
        math_chain=(
            "Of those 440 searches, the top 3 businesses on Google Maps capture about "
            "154 of them. Around 30 of those turn into actual enquiries - phone calls, "
            "quote requests, messages. And roughly 15 become paying jobs."
        ),
        provocative_close=(
            "What's your average job worth? Multiply that by 15. That's what you're "
            "leaving on the table every single month - not to mention the repeat work "
            "and referrals that would come from those jobs."
        ),
        action_items=[
            {
                "name": "Fix your address visibility",
                "explanation": (
                    "Competitors with 13 reviews are outranking you because Google can "
                    "see their street address. Your service area listing is costing you "
                    "the top 3 Maps spots - and the 154 clicks that come with them."
                ),
            },
            {
                "name": "Close the organic gap",
                "explanation": (
                    "You're invisible in organic search while Montgomery and Innovative "
                    "Comms show up twice - once in Maps, once in organic. That's double "
                    "the chances to get the call."
                ),
            },
            {
                "name": "Leverage your review advantage",
                "explanation": (
                    "639 reviews should be your biggest weapon, but right now it's going "
                    "to waste. The right profile optimisation would turn that social proof "
                    "into top 3 visibility."
                ),
            },
            {
                "name": "Optimise your profile completeness",
                "explanation": (
                    "Small gaps in your listing - services, products, attributes - add up. "
                    "Google's algorithm rewards the most complete profiles, and right now "
                    "competitors are ticking boxes you're missing."
                ),
            },
        ],
        closing_bridge=(
            "The data's clear - you've done the hard work building reviews and photos, "
            "but a few fixable gaps are handing your leads to competitors with a fraction "
            "of your reputation."
        ),
    )

    # --- Keyword volumes ---
    keyword_volumes = [
        KeywordVolume(keyword="electrician Neutral Bay", search_volume=170),
        KeywordVolume(keyword="electrician North Sydney", search_volume=140),
        KeywordVolume(keyword="emergency electrician Neutral Bay", search_volume=70),
        KeywordVolume(keyword="emergency electrician North Sydney", search_volume=60),
    ]

    # --- Build ReportData ---
    report_data = ReportData(
        lead=lead,
        suburb_result=suburb_result,
        lga_result=lga_result,
        prospect_score=score,
        analysis=analysis,
        keyword_volumes=keyword_volumes,
    )

    output_path = "output/test-v2.pdf"
    generate_pdf(report_data, output_path)
    print(f"PDF generated: {output_path}")


if __name__ == "__main__":
    main()
