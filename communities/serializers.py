from rest_framework import serializers

from .models import Community, Membership


class CommunitySerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()

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
            'is_public', 'member_count', 'is_member', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_is_member(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Membership.objects.filter(user=request.user, community=obj).exists()
