from rest_framework import serializers

from users.serializers import UserSerializer
from .models import Post, Comment, PollOption, PostImage


class CommentSerializer(serializers.ModelSerializer):
    """
    `parent` is writable (send the id of the comment being replied to to
    create a nested reply; omit/null for a top-level comment). `replies` is
    a read-only recursive tree — the /comments/ GET endpoint only fetches
    top-level comments and this walks down from each one.
    """
    author = UserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['id', 'post', 'author', 'body', 'parent', 'replies', 'like_count', 'is_liked', 'is_accepted', 'created_at']
        read_only_fields = ['id', 'post', 'author', 'created_at', 'is_accepted']

    def get_replies(self, obj):
        # `children_map` (built once by the view — see PostViewSet.comments)
        # holds every comment on the post already grouped by parent_id, so
        # walking the tree here is a dict lookup, not a query. Falls back to
        # a live query only when serializing a comment outside that context
        # (e.g. the create-comment response for a single new reply).
        children_map = self.context.get('children_map')
        if children_map is not None:
            children = children_map.get(obj.id, [])
        else:
            children = list(obj.replies.select_related('author').prefetch_related('likes').order_by('created_at'))
        blocked_ids = self.context.get('blocked_ids')
        if blocked_ids:
            children = [c for c in children if c.author_id not in blocked_ids]
        return CommentSerializer(children, many=True, context=self.context).data

    def get_like_count(self, obj):
        # obj.likes is prefetched by the view (see PostViewSet.comments), so
        # len() on the cached queryset avoids a fresh COUNT per comment —
        # same reasoning as PollOptionSerializer.get_vote_count below.
        if hasattr(obj, '_prefetched_objects_cache') and 'likes' in obj._prefetched_objects_cache:
            return len(obj.likes.all())
        return obj.like_count

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        if hasattr(obj, '_prefetched_objects_cache') and 'likes' in obj._prefetched_objects_cache:
            return any(u.id == request.user.id for u in obj.likes.all())
        return obj.likes.filter(id=request.user.id).exists()

    def validate_parent(self, value):
        post = self.context.get('post')
        if value and post and value.post_id != post.id:
            raise serializers.ValidationError("Can't reply to a comment on a different post.")
        return value


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


class PostImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostImage
        fields = ['id', 'image', 'order']
        read_only_fields = fields


class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    # Gallery images (0-6, uploaded via repeated `images` multipart fields —
    # same pattern as `links`/`tags`/`options` below). `image` (singular)
    # stays for backward compatibility with posts created before the
    # gallery existed; new uploads always go through `images` instead, and
    # the frontend renders `images` when present, falling back to `image`.
    images = PostImageSerializer(many=True, read_only=True)
    like_count = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    # Plain FK field `community` only ever returns the id — this adds the
    # name too so cross-community views (the dashboard's trending carousel
    # in particular) can label "in {community_name}" without a second
    # request per post.
    community_name = serializers.CharField(source='community.name', read_only=True)

    def get_like_count(self, obj):
        return obj.like_count_val if hasattr(obj, 'like_count_val') else obj.like_count

    def get_comment_count(self, obj):
        return obj.comment_count_val if hasattr(obj, 'comment_count_val') else obj.comment_count

    def get_is_saved(self, obj):
        if hasattr(obj, 'is_saved_val'):
            return obj.is_saved_val
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.saved_by.filter(user=request.user).exists()

    # Poll support: write with a plain list of option strings
    # (`poll_options: ["Option A", "Option B"]`), read back as full
    # PollOptionSerializer objects with live vote counts.
    poll_options = PollOptionSerializer(many=True, read_only=True)
    options = serializers.ListField(
        child=serializers.CharField(max_length=150), write_only=True, required=False
    )
    voted_option_id = serializers.SerializerMethodField()

    # Freeform chips on POST-type posts (Knowledge/Project/Resource/etc).
    # Not required for question/poll posts — defaults to an empty list.
    tags = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, default=list
    )

    # Optional external links (see Post.links docstring). Each entry is a
    # "Label|||URL" string — kept flat/stringy like `tags` and `options` so
    # multipart form posts from the composer can send repeated `links`
    # fields without needing a nested JSON body.
    links = serializers.ListField(
        child=serializers.CharField(max_length=300), required=False, default=list
    )

    class Meta:
        model = Post
        fields = [
            'id', 'community', 'community_name', 'author', 'post_type', 'title', 'body', 'image', 'images', 'tags', 'links',
            'like_count', 'comment_count', 'is_liked', 'is_saved', 'is_pinned',
            'poll_options', 'options', 'voted_option_id',
            'is_solved', 'solved_at',
            'created_at', 'updated_at',
        ]
        # is_solved/solved_at are read-only here on purpose — they're only
        # ever changed through PostViewSet.mark_solved (author-only, one-way),
        # never via a plain PATCH, so a stray `is_solved: false` in an edit
        # payload can't accidentally un-solve a question.
        read_only_fields = ['id', 'author', 'is_pinned', 'is_solved', 'solved_at', 'created_at', 'updated_at']

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
