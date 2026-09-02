from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from communities.models import Community
from ._default_images import build_cover_png, build_icon_png


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
        parser.add_argument(
            "--reset-images", action="store_true",
            help="Regenerate icon/cover_image even for communities that already have one.",
        )

    def handle(self, *args, **options):
        # IMPORTANT: no single @transaction.atomic wrapping the whole loop.
        # It used to — which meant if *anything* raised for *any one* item
        # (most likely: the icon/cover .save() call hitting S3 when
        # USE_S3=True but AWS_ACCESS_KEY_ID/SECRET/BUCKET aren't actually
        # filled in on the host yet — those are `sync: false` in render.yaml,
        # i.e. set manually per-environment and easy to forget), Django
        # rolled back the *entire* transaction — every community, even ones
        # already committed earlier in the same run — leaving zero of the
        # ten default communities in the DB. That's the "communities I
        # created by default aren't showing" symptom: the command was
        # failing/rolling back silently on every deploy.
        #
        # Each item now gets its own small atomic block for the DB row, and
        # the icon/cover upload is separately try/excepted: a storage
        # failure logs a warning and moves on instead of undoing the
        # community record. The frontend already has a graceful fallback
        # for a missing icon/cover (a generated gradient + initial, see
        # CommunityCover.jsx), so the community still shows up correctly —
        # just without its custom art — until storage is fixed and
        # `--reset-images` is re-run.
        created, updated, imaged, image_failures = 0, 0, 0, 0
        for item in DEFAULT_COMMUNITIES:
            slug = slugify(item["name"])
            try:
                with transaction.atomic():
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
            except Exception as exc:  # noqa: BLE001 — one bad row must never block the rest
                self.stderr.write(self.style.ERROR(f"Skipped '{item['name']}': {exc}"))
                continue

            # Backfill the generated icon + cover for any default community
            # that's missing one (freshly created ones always are), or force
            # it for every default community when --reset-images is passed.
            needs_icon = options["reset_images"] or not community.icon
            needs_cover = options["reset_images"] or not community.cover_image
            if needs_icon or needs_cover:
                try:
                    file_stub = slug
                    if needs_icon:
                        icon_bytes = build_icon_png(item["color"], item["icon_key"])
                        community.icon.save(f"{file_stub}.png", ContentFile(icon_bytes), save=False)
                    if needs_cover:
                        cover_bytes = build_cover_png(item["color"], item["icon_key"])
                        community.cover_image.save(f"{file_stub}_cover.png", ContentFile(cover_bytes), save=False)
                    community.save(update_fields=["icon", "cover_image"])
                    imaged += 1
                except Exception as exc:  # noqa: BLE001 — image/storage failure shouldn't hide the community
                    image_failures += 1
                    self.stderr.write(self.style.WARNING(
                        f"'{item['name']}' created without icon/cover (image step failed: {exc}). "
                        f"Re-run with --reset-images once storage is fixed."
                    ))

        summary = (
            f"Seed complete — {created} community(ies) created, {updated} updated, "
            f"{imaged} given icon/cover images, "
            f"{len(DEFAULT_COMMUNITIES) - created - updated} already up to date."
        )
        if image_failures:
            summary += f" {image_failures} community(ies) missing icon/cover — see warnings above."
        self.stdout.write(self.style.SUCCESS(summary))
