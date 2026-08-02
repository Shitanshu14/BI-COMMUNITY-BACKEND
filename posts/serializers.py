from rest_framework import serializers

from users.serializers import UserSerializer
from .models import Post, Comment, PollOption


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = Comment
        fields = ['id', 'post', 'author', 'body', 'created_at']
        read_only_fields = ['id', 'post', 'author', 'created_at']


class PollOptionSerializer(serializers.ModelSerializer):
    vote_count = serializers.ReadOnlyField()

    class Meta:
        model = PollOption
        fields = ['id', 'text', 'order', 'vote_count']
        read_only_fields = ['id', 'vote_count']


class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    like_count = serializers.ReadOnlyField()
    comment_count = serializers.ReadOnlyField()
    is_liked = serializers.SerializerMethodField()

    # Poll support: write with a plain list of option strings
    # (`poll_options: ["Option A", "Option B"]`), read back as full
    # PollOptionSerializer objects with live vote counts.
    poll_options = PollOptionSerializer(many=True, read_only=True)
    options = serializers.ListField(
        child=serializers.CharField(max_length=150), write_only=True, required=False
    )
    voted_option_id = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'community', 'author', 'post_type', 'title', 'body', 'image',
            'like_count', 'comment_count', 'is_liked',
            'poll_options', 'options', 'voted_option_id',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'author', 'created_at', 'updated_at']

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.likes.filter(id=request.user.id).exists()

    def get_voted_option_id(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or obj.post_type != Post.PostType.POLL:
            return None
        vote = obj.poll_options.filter(votes=request.user).first()
        return vote.id if vote else None

    def validate(self, attrs):
        post_type = attrs.get('post_type', getattr(self.instance, 'post_type', None))
        options = attrs.get('options')
        if post_type == Post.PostType.POLL and self.instance is None:
            if not options or len(options) < 2:
                raise serializers.ValidationError({'options': 'A poll needs at least 2 options.'})
            if len(options) > 6:
                raise serializers.ValidationError({'options': 'A poll can have at most 6 options.'})
        return attrs

    def create(self, validated_data):
        options = validated_data.pop('options', None)
        post = Post.objects.create(**validated_data)
        if post.post_type == Post.PostType.POLL and options:
            PollOption.objects.bulk_create([
                PollOption(post=post, text=text, order=i) for i, text in enumerate(options)
            ])
        return post
