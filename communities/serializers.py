from django.utils.text import slugify
from rest_framework import serializers

from .models import Community, Membership


class CommunitySerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    is_pending = serializers.SerializerMethodField()
    # BUG FIX: `slug` is a required, unique SlugField on the model. The
    # Django Admin form auto-fills it via `prepopulated_fields`, but any
    # other client hitting POST /api/communities/ directly (a future admin
    # dashboard, a script, a mobile app) got a hard 400 "This field is
    # required." with no way to know what value was expected. Making it
    # optional here and deriving it from `name` when omitted matches what
    # the Admin already does, and still lets a caller pass a custom slug.
    slug = serializers.SlugField(max_length=110, required=False)

    def get_member_count(self, obj):
        # Present when the queryset was annotated (list/retrieve via the
        # viewset) — avoids an extra query per row. Falls back to the
        # property for cases where a plain model instance is serialized
        # directly (e.g. join/leave action responses).
        if hasattr(obj, 'member_count_val'):
            return obj.member_count_val
        return obj.member_count

    class Meta:
        model = Community
        fields = [
            'id', 'name', 'slug', 'description', 'icon', 'rules',
            'is_public', 'join_mode', 'is_on_hold', 'member_count',
            'is_member', 'is_pending', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'is_on_hold']

    def validate(self, attrs):
        # Auto-derive the slug from the name when the caller didn't supply
        # one, uniquifying with a numeric suffix on collision (same
        # approach Django Admin effectively gets for free from the JS
        # prepopulate widget, which the raw API doesn't get).
        if not attrs.get('slug'):
            name = attrs.get('name') or (self.instance.name if self.instance else '')
            base_slug = slugify(name)[:110] or 'community'
            slug = base_slug
            qs = Community.objects.exclude(pk=getattr(self.instance, 'pk', None))
            suffix = 2
            while qs.filter(slug=slug).exists():
                suffix_str = f'-{suffix}'
                slug = f'{base_slug[:110 - len(suffix_str)]}{suffix_str}'
                suffix += 1
            attrs['slug'] = slug
        return attrs

    def get_is_member(self, obj):
        if hasattr(obj, 'is_member_val'):
            return obj.is_member_val
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Membership.objects.filter(
            user=request.user, community=obj, status=Membership.Status.APPROVED
        ).exists()

    def get_is_pending(self, obj):
        if hasattr(obj, 'is_pending_val'):
            return obj.is_pending_val
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Membership.objects.filter(
            user=request.user, community=obj, status=Membership.Status.PENDING
        ).exists()
