from django.db.models import Count, Exists, OuterRef
from django.utils import timezone
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from communities.models import Membership
from notifications.models import Notification
from notifications.tasks import create_notification
from users.models import Block
from .models import Post, Comment, PollOption, PollVote
from .serializers import PostSerializer, CommentSerializer


class IsAuthorOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author == request.user


def blocked_user_ids(user):
    """IDs to hide from `user`: anyone they blocked, and anyone who blocked
    them — blocking is one-directional to record, but its effect (hiding
    each other's content) is mutual everywhere it's applied."""
    if not user or not user.is_authenticated:
        return set()
    blocked = Block.objects.filter(blocker=user).values_list('blocked_id', flat=True)
    blocked_by = Block.objects.filter(blocked=user).values_list('blocker_id', flat=True)
    return set(blocked) | set(blocked_by)


class PostViewSet(viewsets.ModelViewSet):
    """
    /api/posts/?community=<id>   -> feed for a community
    /api/posts/?community=<id>&type=question   -> feed filtered to one post_type
                                                    (question | post | poll)
    /api/posts/?author=<id>      -> a specific user's posts (profile page grid)
    /api/posts/<id>/like/        -> POST toggle like
    /api/posts/<id>/comments/    -> GET list / POST create comment (nested replies via `parent`)
    /api/posts/<id>/pin/         -> POST toggle pinned (community admin/moderator only)
    """
    # Base queryset stays select_related-only here; the heavier annotations
    # (Count, Exists) are applied per-request in get_queryset() below, since
    # is_liked_val depends on the requesting user.
    queryset = Post.objects.select_related('author', 'community').prefetch_related('poll_options__votes')
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset().filter(author__is_active=True)

        user = self.request.user
        hidden_ids = blocked_user_ids(user)
        if hidden_ids:
            qs = qs.exclude(author_id__in=hidden_ids)

        community_id = self.request.query_params.get('community')
        if community_id:
            qs = qs.filter(community_id=community_id)
        author_id = self.request.query_params.get('author')
        if author_id:
            qs = qs.filter(author_id=author_id)
        post_type = self.request.query_params.get('type')
        if post_type in dict(Post.PostType.choices):
            qs = qs.filter(post_type=post_type)

        # Previously like_count/comment_count/is_liked were each a property
        # or a per-object .filter().exists() call — for a 20-post feed page
        # that's up to 60 extra queries. Annotating once here brings a feed
        # page back down to a small, fixed number of queries regardless of
        # page size.
        qs = qs.annotate(
            like_count_val=Count('likes', distinct=True),
            comment_count_val=Count('comments', distinct=True),
        )
        if user.is_authenticated:
            qs = qs.annotate(
                is_liked_val=Exists(
                    Post.likes.through.objects.filter(post_id=OuterRef('pk'), user_id=user.id)
                )
            )
        # Pinned posts float to the top of every feed, newest first within
        # each group (matches Post.Meta.ordering, kept explicit here since
        # the queryset also gets other filters/annotations applied above).
        return qs.order_by('-is_pinned', '-created_at')

    def perform_create(self, serializer):
        community = serializer.validated_data.get('community')
        if community and not Membership.objects.filter(user=self.request.user, community=community).exists():
            raise PermissionDenied('Join this community before posting in it.')
        serializer.save(author=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        post = self.get_object()
        if post.likes.filter(id=request.user.id).exists():
            post.likes.remove(request.user)
            liked = False
        else:
            post.likes.add(request.user)
            liked = True
            create_notification.delay(
                recipient_id=str(post.author_id),
                verb=Notification.Verb.POST_LIKED,
                actor_id=str(request.user.id),
                target_id=str(post.id),
            )
        return Response({'liked': liked, 'like_count': post.like_count})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def pin(self, request, pk=None):
        """POST /api/posts/<id>/pin/ — toggles is_pinned. Only a moderator/
        admin of the post's community (or Django staff) may pin/unpin."""
        post = self.get_object()
        membership = Membership.objects.filter(user=request.user, community=post.community).first()
        is_mod = membership is not None and membership.role in (Membership.Role.ADMIN, Membership.Role.MODERATOR)
        if not (is_mod or request.user.is_staff):
            raise PermissionDenied('Only a community admin or moderator can pin posts.')

        post.is_pinned = not post.is_pinned
        post.pinned_at = timezone.now() if post.is_pinned else None
        post.save(update_fields=['is_pinned', 'pinned_at'])
        return Response({'is_pinned': post.is_pinned})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def vote(self, request, pk=None):
        """POST /api/posts/<id>/vote/  body: {option_id} — one vote per user;
        voting for a different option moves the existing vote."""
        post = self.get_object()
        if post.post_type != Post.PostType.POLL:
            return Response({'detail': 'This post is not a poll.'}, status=400)

        option_id = request.data.get('option_id')
        option = post.poll_options.filter(id=option_id).first()
        if not option:
            return Response({'detail': 'Invalid option for this poll.'}, status=400)

        PollVote.objects.filter(option__post=post, user=request.user).delete()
        PollVote.objects.create(option=option, user=request.user)

        options = [
            {'id': str(o.id), 'text': o.text, 'vote_count': o.vote_count}
            for o in post.poll_options.all()
        ]
        return Response({'voted_option_id': str(option.id), 'options': options})

    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticated])
    def comments(self, request, pk=None):
        post = self.get_object()
        hidden_ids = blocked_user_ids(request.user)

        if request.method == 'GET':
            # Only top-level comments here — each one's `replies` field
            # recursively serializes its own children (see CommentSerializer).
            qs = post.comments.filter(parent__isnull=True).select_related('author')
            if hidden_ids:
                qs = qs.exclude(author_id__in=hidden_ids)
            serializer = CommentSerializer(qs, many=True, context={'request': request, 'blocked_ids': hidden_ids})
            return Response(serializer.data)

        serializer = CommentSerializer(data=request.data, context={'request': request, 'post': post, 'blocked_ids': hidden_ids})
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(author=request.user, post=post)

        # A reply notifies the parent comment's author; a top-level comment
        # notifies the post's author (skip either if that'd notify yourself).
        if comment.parent_id and comment.parent.author_id != request.user.id:
            create_notification.delay(
                recipient_id=str(comment.parent.author_id),
                verb=Notification.Verb.COMMENT_REPLIED,
                actor_id=str(request.user.id),
                target_id=str(post.id),
            )
        elif not comment.parent_id and post.author_id != request.user.id:
            create_notification.delay(
                recipient_id=str(post.author_id),
                verb=Notification.Verb.POST_COMMENTED,
                actor_id=str(request.user.id),
                target_id=str(post.id),
            )
        return Response(serializer.data, status=201)
