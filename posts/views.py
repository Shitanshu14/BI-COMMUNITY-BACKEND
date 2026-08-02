from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from notifications.models import Notification
from notifications.tasks import create_notification
from .models import Post, Comment, PollOption, PollVote
from .serializers import PostSerializer, CommentSerializer


class IsAuthorOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author == request.user


class PostViewSet(viewsets.ModelViewSet):
    """
    /api/posts/?community=<id>   -> feed for a community
    /api/posts/?author=<id>      -> a specific user's posts (profile page grid)
    /api/posts/<id>/like/        -> POST toggle like
    /api/posts/<id>/comments/    -> GET list / POST create comment
    """
    queryset = Post.objects.select_related('author', 'community').all()
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsAuthorOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        community_id = self.request.query_params.get('community')
        if community_id:
            qs = qs.filter(community_id=community_id)
        author_id = self.request.query_params.get('author')
        if author_id:
            qs = qs.filter(author_id=author_id)
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
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

    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticatedOrReadOnly])
    def comments(self, request, pk=None):
        post = self.get_object()
        if request.method == 'GET':
            serializer = CommentSerializer(post.comments.select_related('author'), many=True)
            return Response(serializer.data)

        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(author=request.user, post=post)
        create_notification.delay(
            recipient_id=str(post.author_id),
            verb=Notification.Verb.POST_COMMENTED,
            actor_id=str(request.user.id),
            target_id=str(post.id),
        )
        return Response(serializer.data, status=201)
