from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Community, Membership

User = get_user_model()


class CommunityCreationTests(APITestCase):
    """Community creation stays admin/staff-only — regular users create
    Circles instead (see circles/views.py), not Communities."""

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pass12345')
        self.staff = User.objects.create_user(
            username='staffer', email='staffer@example.com', password='pass12345', is_staff=True
        )

    def test_regular_user_cannot_create_community(self):
        self.client.force_authenticate(self.user)
        res = self.client.post('/api/communities/', {'name': 'My New Club', 'description': 'test'})
        self.assertEqual(res.status_code, 403, res.data)

    def test_staff_can_create_community(self):
        self.client.force_authenticate(self.staff)
        res = self.client.post('/api/communities/', {'name': 'Staff Club', 'description': 'test'})
        self.assertEqual(res.status_code, 201, res.data)
        community = Community.objects.get(name='Staff Club')
        # Creator is auto-joined as an approved admin.
        membership = Membership.objects.get(user=self.staff, community=community)
        self.assertEqual(membership.role, Membership.Role.ADMIN)
        self.assertEqual(membership.status, Membership.Status.APPROVED)
        self.assertEqual(community.member_count, 1)

    def test_anonymous_cannot_create_community(self):
        res = self.client.post('/api/communities/', {'name': 'Nope'})
        self.assertEqual(res.status_code, 401)


class RegistrationBasedJoinTests(APITestCase):
    """A community created with join_mode='approval' ('registration
    based') should hold new joiners as pending until an admin approves
    them — they shouldn't count as members or see private content yet."""

    def setUp(self):
        self.owner = User.objects.create_user(username='owner', email='owner@example.com', password='pass12345')
        self.joiner = User.objects.create_user(username='joiner', email='joiner@example.com', password='pass12345')
        self.community = Community.objects.create(
            name='Private Club', slug='private-club', is_public=False,
            join_mode=Community.JoinMode.APPROVAL, created_by=self.owner,
        )
        Membership.objects.create(user=self.owner, community=self.community, role=Membership.Role.ADMIN)

    def test_join_creates_pending_membership_not_full_membership(self):
        self.client.force_authenticate(self.joiner)
        res = self.client.post(f'/api/communities/{self.community.id}/join/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'pending')
        membership = Membership.objects.get(user=self.joiner, community=self.community)
        self.assertEqual(membership.status, Membership.Status.PENDING)
        # Still just the owner — a pending request doesn't count.
        self.assertEqual(self.community.member_count, 1)

    def test_pending_member_cannot_see_private_posts(self):
        from posts.models import Post
        Post.objects.create(
            community=self.community, author=self.owner, post_type=Post.PostType.POST,
            title='Members only', body='secret', tags=['General'],
        )
        self.client.force_authenticate(self.joiner)
        self.client.post(f'/api/communities/{self.community.id}/join/')
        res = self.client.get(f'/api/posts/?community={self.community.id}')
        items = res.data if isinstance(res.data, list) else res.data.get('results', [])
        self.assertEqual(len(items), 0)

    def test_admin_can_approve_pending_request(self):
        self.client.force_authenticate(self.joiner)
        self.client.post(f'/api/communities/{self.community.id}/join/')

        self.client.force_authenticate(self.owner)
        res = self.client.post(f'/api/communities/{self.community.id}/join_requests/{self.joiner.id}/approve/')
        self.assertEqual(res.status_code, 200)
        membership = Membership.objects.get(user=self.joiner, community=self.community)
        self.assertEqual(membership.status, Membership.Status.APPROVED)
        self.assertEqual(self.community.member_count, 2)

    def test_non_admin_cannot_view_join_requests(self):
        self.client.force_authenticate(self.joiner)
        self.client.post(f'/api/communities/{self.community.id}/join/')
        res = self.client.get(f'/api/communities/{self.community.id}/join_requests/')
        self.assertEqual(res.status_code, 403)


class OpenCommunityJoinTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner2', email='owner2@example.com', password='pass12345')
        self.joiner = User.objects.create_user(username='joiner2', email='joiner2@example.com', password='pass12345')
        self.community = Community.objects.create(name='Open Club', slug='open-club', created_by=self.owner)
        Membership.objects.create(user=self.owner, community=self.community, role=Membership.Role.ADMIN)

    def test_open_join_is_immediate(self):
        self.client.force_authenticate(self.joiner)
        res = self.client.post(f'/api/communities/{self.community.id}/join/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'joined')
        self.assertEqual(self.community.member_count, 2)


class InteractionRequiresMembershipTests(APITestCase):
    """Reading a public community's posts never required joining, but
    *acting* on them — like, comment, vote, react — always should, even
    in an open community. A private community stays fully unreadable and
    untouchable to non-members."""

    def setUp(self):
        from posts.models import Post

        self.owner = User.objects.create_user(username='owner3', email='owner3@example.com', password='pass12345')
        self.outsider = User.objects.create_user(username='outsider', email='outsider@example.com', password='pass12345')

        self.open_community = Community.objects.create(name='Open Co', slug='open-co', is_public=True, created_by=self.owner)
        Membership.objects.create(user=self.owner, community=self.open_community, role=Membership.Role.ADMIN)
        self.open_post = Post.objects.create(
            community=self.open_community, author=self.owner, post_type=Post.PostType.POST,
            title='Open post', body='hello', tags=['General'],
        )

        self.private_community = Community.objects.create(
            name='Private Co', slug='private-co', is_public=False, created_by=self.owner,
        )
        Membership.objects.create(user=self.owner, community=self.private_community, role=Membership.Role.ADMIN)
        self.private_post = Post.objects.create(
            community=self.private_community, author=self.owner, post_type=Post.PostType.POST,
            title='Private post', body='secret', tags=['General'],
        )

    def test_non_member_can_read_open_community_post_but_not_like_it(self):
        self.client.force_authenticate(self.outsider)
        res = self.client.get('/api/posts/', {'community': str(self.open_community.id)})
        items = res.data if isinstance(res.data, list) else res.data.get('results', [])
        self.assertEqual(len(items), 1)

        res = self.client.post(f'/api/posts/{self.open_post.id}/like/')
        self.assertEqual(res.status_code, 403)

    def test_non_member_cannot_comment_or_vote_on_open_post(self):
        self.client.force_authenticate(self.outsider)
        res = self.client.post(f'/api/posts/{self.open_post.id}/comments/', {'body': 'hi'})
        self.assertEqual(res.status_code, 403)

    def test_member_can_like_open_post_after_joining(self):
        self.client.force_authenticate(self.outsider)
        self.client.post(f'/api/communities/{self.open_community.id}/join/')
        res = self.client.post(f'/api/posts/{self.open_post.id}/like/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['liked'])

    def test_non_member_cannot_read_or_touch_private_post(self):
        self.client.force_authenticate(self.outsider)
        res = self.client.get('/api/posts/', {'community': str(self.private_community.id)})
        items = res.data if isinstance(res.data, list) else res.data.get('results', [])
        self.assertEqual(len(items), 0)
        # Not even reachable to like — get_object() 404s since the base
        # queryset already excludes it for a non-member.
        res = self.client.post(f'/api/posts/{self.private_post.id}/like/')
        self.assertEqual(res.status_code, 404)

    def test_non_member_cannot_see_private_community_member_list(self):
        self.client.force_authenticate(self.outsider)
        res = self.client.get(f'/api/communities/{self.private_community.id}/members/')
        self.assertEqual(res.status_code, 403)

    def test_anyone_can_see_open_community_member_list(self):
        self.client.force_authenticate(self.outsider)
        res = self.client.get(f'/api/communities/{self.open_community.id}/members/')
        self.assertEqual(res.status_code, 200)
