from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from communities.models import Community


# The default communities every fresh install ships with — matches the
# "My Communities / Discover Communities / Trending" dashboard mockup 1:1
# (name, category, blurb, and the vanity member count shown on the cards).
# `icon_key` / `color` drive the CSS-only badge + cover gradient on the
# frontend (see CommunityCard.jsx) since we don't ship real photography —
# an admin can always replace either with a real uploaded image (including
# an animated .gif) from the community's settings later; that upload just
# overrides the generated look.
DEFAULT_COMMUNITIES = [
    {
        "name": "YouTube", "category": Community.Category.TECHNOLOGY, "is_verified": True,
        "description": "A community for creators, learners and enthusiasts.",
        "rules": "Be respectful.\nNo spam or self-promo outside the pinned thread.\nCredit original creators.",
        "boost": 2400, "icon_key": "youtube", "color": "#FF3B3B",
    },
    {
        "name": "Web Development", "category": Community.Category.TECHNOLOGY, "is_verified": True,
        "description": "Learn, discuss and build amazing web projects.",
        "rules": "Keep it constructive.\nUse code blocks for snippets.\nNo unpaid job spam.",
        "boost": 1800, "icon_key": "code", "color": "#4F46E5",
    },
    {
        "name": "AI Automation", "category": Community.Category.TECHNOLOGY, "is_verified": True,
        "description": "Explore AI tools, automation and workflows.",
        "rules": "Share what actually worked for you.\nNo unlabelled AI-generated spam.",
        "boost": 1500, "icon_key": "robot", "color": "#0EA5E9",
    },
    {
        "name": "BGMI INDIA", "category": Community.Category.GAMING, "is_verified": True,
        "description": "Official community for BGMI lovers.",
        "rules": "No hacking / cheat talk.\nSquad-finding goes in the pinned thread.",
        "boost": 1100, "icon_key": "gaming", "color": "#1F2937",
    },
    {
        "name": "Instagram Community", "category": Community.Category.SOCIAL, "is_verified": False,
        "description": "Tips, tricks and strategies to grow on Instagram.",
        "rules": "No follow-for-follow spam.\nGive credit when sharing others' work.",
        "boost": 1600, "icon_key": "instagram", "color": "#C13584",
    },
    {
        "name": "Facebook Community", "category": Community.Category.SOCIAL, "is_verified": False,
        "description": "Connect, share and grow together on Facebook.",
        "rules": "Be kind.\nNo misinformation.",
        "boost": 1300, "icon_key": "facebook", "color": "#1877F2",
    },
    {
        "name": "Biology", "category": Community.Category.EDUCATION, "is_verified": False,
        "description": "For biology learners and enthusiasts.",
        "rules": "Cite sources for claims.\nHomework help welcome, homework-doing is not.",
        "boost": 968, "icon_key": "biology", "color": "#059669",
    },
    {
        "name": "Teacher Community", "category": Community.Category.EDUCATION, "is_verified": False,
        "description": "Resources, ideas and teaching strategies for teachers.",
        "rules": "Keep resources free to share.\nNo student data, ever.",
        "boost": 968, "icon_key": "teacher", "color": "#EA580C",
    },
    {
        "name": "Influencer Community", "category": Community.Category.SOCIAL, "is_verified": False,
        "description": "For content creators and influencers to grow.",
        "rules": "No brand-deal spam outside the pinned thread.",
        "boost": 1100, "icon_key": "star", "color": "#7C3AED",
    },
    {
        "name": "Business Network", "category": Community.Category.BUSINESS, "is_verified": True,
        "description": "Network and grow your business together.",
        "rules": "No cold-pitching in DMs.\nDisclose paid partnerships.",
        "boost": 1200, "icon_key": "business", "color": "#0F172A",
    },
]


class Command(BaseCommand):
    help = "Creates the default set of communities shown in the dashboard mockups (idempotent — safe to re-run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-boost", action="store_true",
            help="Also overwrite member_count_boost/category/description on communities that already exist.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        created, updated = 0, 0
        for item in DEFAULT_COMMUNITIES:
            slug = slugify(item["name"])
            community, was_created = Community.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "rules": item["rules"],
                    "category": item["category"],
                    "is_verified": item["is_verified"],
                    "member_count_boost": item["boost"],
                    "is_public": True,
                },
            )
            if was_created:
                created += 1
            elif options["reset_boost"]:
                community.description = item["description"]
                community.category = item["category"]
                community.is_verified = item["is_verified"]
                community.member_count_boost = item["boost"]
                community.save(update_fields=["description", "category", "is_verified", "member_count_boost"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete — {created} community(ies) created, {updated} updated, "
            f"{len(DEFAULT_COMMUNITIES) - created - updated} already up to date."
        ))
