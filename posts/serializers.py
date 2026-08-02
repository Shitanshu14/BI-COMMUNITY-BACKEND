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
    vote_count = serializers.SerializerMethodField()

    class Meta:
        model = PollOption
        fields = ['id', 'text', 'order', 'vote_count']
        read_only_fields = ['id', 'vote_count']

    def get_vote_count(self, obj):
        # When the post queryset prefetches 'poll_options__votes', obj.votes
        # is already cached in memory — len() on it reuses that cache
        # instead of firing a fresh COUNT query per option.
        if hasattr(obj, '_prefetched_objects_cache') and 'votes' in obj._prefetched_objects_cache:
            return len(obj.votes.all())
        return obj.vote_count


class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    like_count = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()

    def get_like_count(self, obj):
        return obj.like_count_val if hasattr(obj, 'like_count_val') else obj.like_count

    def get_comment_count(self, obj):
        return obj.comment_count_val if hasattr(obj, 'comment_count_val') else obj.comment_count

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
        if hasattr(obj, 'is_liked_val'):
            return obj.is_liked_val
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
