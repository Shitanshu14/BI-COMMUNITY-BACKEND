from rest_framework import serializers

from .models import Community, Membership


class CommunitySerializer(serializers.ModelSerializer):
    member_count = serializers.ReadOnlyField()
    is_member = serializers.SerializerMethodField()

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
