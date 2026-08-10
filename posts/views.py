import datetime

from django.db.models import Count, Exists, ExpressionWrapper, F, IntegerField, OuterRef, Q
from django.utils import timezone
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from communities.models import Membership
from notifications.models import Notification
from notifications.tasks import create_notification
from users.models import Block
from .models import Post, PollVote, SavedPost
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
    /api/posts/?community=<id>&sort=trending   -> feed ranked by engagement from
                                                    the last 7 days instead of newest-first
    /api/posts/?author=<id>      -> a specific user's posts (profile page grid)
    /api/posts/<id>/like/        -> POST toggle like
    /api/posts/<id>/comments/    -> GET list / POST create comment (nested replies via `parent`)
    /api/posts/<id>/pin/         -> POST toggle pinned (community admin/moderator only)
    /api/posts/<id>/mark_solved/ -> POST one-way solve for a QUESTION post (author only)
    """

    # How far back "trending" looks. Without this window an old post that
    # picked up a lot of likes/comments over months would permanently
    # outrank anything posted this week, so trending only ever considers
    # recent activity — same idea as Reddit/HN's "hot" ranking.
    TRENDING_WINDOW = datetime.timedelta(days=7)
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

        # Private communities' posts are only visible to their own members.
        # Previously this had no check at all — anyone authenticated could
        # read any private community's feed by passing its id in ?community=,
        # and a community-less query (the global/trending feed below) would
        # have leaked private posts to every logged-in user. Public
        # communities are unaffected. Exists() rather than a join+distinct()
        # to avoid M2M join fan-out duplicating rows under the Count()
        # annotations further down.
        qs = qs.filter(
            Q(community__is_public=True) |
            Exists(Membership.objects.filter(community_id=OuterRef('community_id'), user_id=user.id))
        )

        community_id = self.request.query_params.get('community')
        if community_id:
            qs = qs.filter(community_id=community_id)
        author_id = self.request.query_params.get('author')
        if author_id:
            qs = qs.filter(author_id=author_id)
        post_type = self.request.query_params.get('type')
        if post_type in dict(Post.PostType.choices):
            qs = qs.filter(post_type=post_type)
        if self.request.query_params.get('saved') == 'true' and user.is_authenticated:
            qs = qs.filter(saved_by__user=user)

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
                ),
                is_saved_val=Exists(
                    SavedPost.objects.filter(post_id=OuterRef('pk'), user_id=user.id)
                ),
            )
        if self.request.query_params.get('sort') == 'trending':
            # Simple, cross-database-safe "hot" score built from the
            # like_count_val/comment_count_val annotations already applied
            # above (weighting comments higher than likes — leaving a
            # comment is a stronger engagement signal than a tap). Reusing
            # those existing Count(..., distinct=True) annotations instead
            # of aggregating again here avoids the classic Django trap of
            # stacking two separate Count()s over different reverse
            # relations in one annotate() call, which silently inflates
            # both counts via join fan-out. Only posts from the trending
            # window are ranked at all; pinned posts still float to the top.
            qs = qs.filter(created_at__gte=timezone.now() - self.TRENDING_WINDOW).annotate(
                trending_score_val=ExpressionWrapper(
                    F('like_count_val') * 2 + F('comment_count_val') * 3,
                    output_field=IntegerField(),
                )
            )
            return qs.order_by('-is_pinned', '-trending_score_val', '-created_at')

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

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated], url_path='save')
    def save_post(self, request, pk=None):
        """POST /api/posts/<id>/save/ — toggle bookmark for the current
        user. Kept separate from `like` (public, notifies the author) —
        saving is private and author-invisible, more like a personal
        reading-list entry. (Named save_post since ViewSet already has a
        DRF-internal `.save`-adjacent machinery on the serializer, not the
        view — this avoids any confusion reading the two side by side.)"""
        post = self.get_object()
        saved_qs = SavedPost.objects.filter(post=post, user=request.user)
        if saved_qs.exists():
            saved_qs.delete()
            saved = False
        else:
            SavedPost.objects.create(post=post, user=request.user)
            saved = True
        return Response({'saved': saved})

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
    def mark_solved(self, request, pk=None):
        """POST /api/posts/<id>/mark_solved/ — the asker flags their own
        QUESTION post as solved. Deliberately one-way: once is_solved is
        True this just returns that same state instead of flipping it back,
        so "Mark solved" can never be clicked into "unsolved" by mistake —
        the frontend swaps the button for a permanent "Solved" badge as
        soon as this returns is_solved: true."""
        post = self.get_object()
        if post.author_id != request.user.id:
            raise PermissionDenied('Only the person who asked can mark this solved.')
        if post.post_type != Post.PostType.QUESTION:
            return Response({'detail': 'Only questions can be marked solved.'}, status=400)

        if not post.is_solved:
            post.is_solved = True
            post.solved_at = timezone.now()
            post.save(update_fields=['is_solved', 'solved_at'])

        return Response({'is_solved': post.is_solved, 'solved_at': post.solved_at})

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
            # prefetch_related('likes') lets CommentSerializer read
            # like_count/is_liked from the cache instead of a query per
            # comment (and per reply, recursively).
            qs = post.comments.filter(parent__isnull=True).select_related('author').prefetch_related('likes')
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

    @action(
        detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated],
        url_path='comments/(?P<comment_id>[^/.]+)/like',
    )
    def like_comment(self, request, pk=None, comment_id=None):
        """POST /api/posts/<post_id>/comments/<comment_id>/like/ — toggle
        like on one comment. Scoped under the post's own detail route
        (rather than a standalone /api/comments/<id>/like/) so a single
        get_object() call also confirms the comment actually belongs to
        this post, matching how replies are validated in CommentSerializer.
        """
        post = self.get_object()
        comment = post.comments.filter(id=comment_id).first()
        if not comment:
            return Response({'detail': 'Comment not found on this post.'}, status=404)

        if comment.likes.filter(id=request.user.id).exists():
            comment.likes.remove(request.user)
            liked = False
        else:
            comment.likes.add(request.user)
            liked = True
            if comment.author_id != request.user.id:
                create_notification.delay(
                    recipient_id=str(comment.author_id),
                    verb=Notification.Verb.COMMENT_LIKED,
                    actor_id=str(request.user.id),
                    target_id=str(post.id),
                )
        return Response({'liked': liked, 'like_count': comment.like_count})
