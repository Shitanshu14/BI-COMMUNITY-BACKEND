from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from communities.models import Community
from communities.serializers import CommunitySerializer
from posts.models import Post
from posts.serializers import PostSerializer
from posts.views import blocked_user_ids
from users.serializers import UserSerializer

User = get_user_model()


class GlobalSearchView(APIView):
    """
    GET /api/search/?q=<text>&type=all|users|posts|communities

    Powers the search bar — one call returns matching users, posts, and
    communities together (type=all, the default) so the dropdown can show
    a few of each; pass type=users/posts/communities for a dedicated
    "see all results" page with a bigger per-type limit.

    Requires login, same as the rest of the app. Deactivated accounts and
    anyone involved in a block with the requester are excluded from every
    section, same rules as the feed (see posts/views.blocked_user_ids).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        query = (request.query_params.get('q') or '').strip()
        search_type = request.query_params.get('type', 'all')
        limit = 8 if search_type == 'all' else 30

        empty = {'users': [], 'posts': [], 'communities': []}
        if not query:
            return Response(empty)

        hidden_ids = blocked_user_ids(request.user)
        result = {}

        if search_type in ('all', 'users'):
            users_qs = User.objects.filter(is_active=True).exclude(id__in=hidden_ids).filter(
                Q(username__icontains=query) | Q(headline__icontains=query) | Q(bio__icontains=query)
            ).order_by('username')[:limit]
            result['users'] = UserSerializer(users_qs, many=True, context={'request': request}).data

        if search_type in ('all', 'posts'):
            posts_qs = Post.objects.filter(author__is_active=True).exclude(author_id__in=hidden_ids).filter(
                Q(title__icontains=query) | Q(body__icontains=query)
            ).select_related('author', 'community').order_by('-created_at')[:limit]
            result['posts'] = PostSerializer(posts_qs, many=True, context={'request': request}).data

        if search_type in ('all', 'communities'):
            comms_qs = Community.objects.filter(
                Q(name__icontains=query) | Q(description__icontains=query)
            ).order_by('name')[:limit]
            result['communities'] = CommunitySerializer(comms_qs, many=True, context={'request': request}).data

        return Response(result)
