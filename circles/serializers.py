from rest_framework import serializers

from users.serializers import UserSerializer
from .models import Circle, CircleMembership, CircleInvite, CircleQuestion, CircleAnswer


class CircleSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()

    def get_member_count(self, obj):
        if hasattr(obj, 'member_count_val'):
            return obj.member_count_val
        return obj.member_count

    def get_is_member(self, obj):
        if hasattr(obj, 'is_member_val'):
            return obj.is_member_val
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return CircleMembership.objects.filter(user=request.user, circle=obj).exists()

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return CircleMembership.objects.filter(
            user=request.user, circle=obj, role=CircleMembership.Role.OWNER
        ).exists()

    class Meta:
        model = Circle
        fields = [
            'id', 'name', 'description', 'icon', 'max_members',
            'member_count', 'is_member', 'is_owner', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class CircleInviteSerializer(serializers.ModelSerializer):
    circle = CircleSerializer(read_only=True)
    invited_by = UserSerializer(read_only=True)
    invited_user = UserSerializer(read_only=True)

    class Meta:
        model = CircleInvite
        fields = ['id', 'circle', 'invited_user', 'invited_by', 'status', 'created_at', 'responded_at']
        read_only_fields = fields


class CircleAnswerSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = CircleAnswer
        fields = ['id', 'question', 'author', 'body', 'created_at', 'is_accepted']
        read_only_fields = ['id', 'question', 'author', 'created_at', 'is_accepted']


class CircleQuestionSerializer(serializers.ModelSerializer):
    """List/create shape — no nested answers, just a count, so the board
    stays cheap to load with many questions."""
    author = UserSerializer(read_only=True)
    answer_count = serializers.SerializerMethodField()

    def get_answer_count(self, obj):
        if hasattr(obj, 'answer_count_val'):
            return obj.answer_count_val
        return obj.answer_count

    class Meta:
        model = CircleQuestion
        fields = ['id', 'circle', 'author', 'title', 'body', 'created_at', 'is_solved', 'answer_count']
        read_only_fields = ['id', 'circle', 'author', 'created_at', 'is_solved', 'answer_count']


class CircleQuestionDetailSerializer(CircleQuestionSerializer):
    """Single-question view — full answer thread included."""
    answers = CircleAnswerSerializer(many=True, read_only=True)

    class Meta(CircleQuestionSerializer.Meta):
        fields = CircleQuestionSerializer.Meta.fields + ['answers']
