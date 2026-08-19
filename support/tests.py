from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from communities.models import Community, Membership
from circles.models import Circle, CircleMembership

User = get_user_model()


def make_user(username, email, **kwargs):
    return User.objects.create_user(username=username, email=email, password="TestPass123!", **kwargs)


class SupportAccessTests(APITestCase):
    def setUp(self):
        self.regular = make_user("regular_u", "regular_u@example.com")
        self.support = make_user("support_u", "support_u@example.com", is_support=True)
        self.staff = make_user("staff_u", "staff_u@example.com", is_staff=True)

    def test_regular_user_cannot_access_stats(self):
        self.client.force_authenticate(user=self.regular)
        resp = self.client.get("/api/support/stats/")
        self.assertEqual(resp.status_code, 403)

    def test_support_user_can_access_stats(self):
        self.client.force_authenticate(user=self.support)
        resp = self.client.get("/api/support/stats/")
        self.assertEqual(resp.status_code, 200)
        for key in ("total_users", "active_users", "blocked_users", "total_communities", "total_circles", "pending_verifications"):
            self.assertIn(key, resp.json())

    def test_staff_user_can_access_stats(self):
        self.client.force_authenticate(user=self.staff)
        resp = self.client.get("/api/support/stats/")
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_cannot_access_stats(self):
        resp = self.client.get("/api/support/stats/")
        self.assertIn(resp.status_code, (401, 403))

    def test_me_endpoint_exposes_is_support_only_to_self(self):
        self.client.force_authenticate(user=self.support)
        resp = self.client.get("/api/users/me/")
        self.assertTrue(resp.json()["is_support"])

        # Someone else viewing this support user's public profile shouldn't
        # see is_support at all (it's not on UserProfileSerializer).
        other = make_user("viewer_u", "viewer_u@example.com")
        self.client.force_authenticate(user=other)
        resp = self.client.get(f"/api/users/{self.support.id}/")
        self.assertNotIn("is_support", resp.json())


class SupportUserListTests(APITestCase):
    def setUp(self):
        self.support = make_user("support_list", "support_list@example.com", is_support=True)
        self.alice = make_user("alice_list", "alice_list@example.com")
        self.bob = make_user("bob_list", "bob_list@example.com", is_active=False)
        self.client.force_authenticate(user=self.support)

    def test_search_by_username(self):
        resp = self.client.get("/api/support/users/?q=alice_list")
        rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["username"], "alice_list")

    def test_filter_blocked(self):
        resp = self.client.get("/api/support/users/?status=blocked")
        rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        usernames = [r["username"] for r in rows]
        self.assertIn("bob_list", usernames)
        self.assertNotIn("alice_list", usernames)

    def test_counts_are_present(self):
        community = Community.objects.create(name="Support Count Test")
        Membership.objects.create(user=self.alice, community=community)
        resp = self.client.get("/api/support/users/?q=alice_list")
        rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        self.assertEqual(rows[0]["community_count"], 1)


class SupportBlockUnblockTests(APITestCase):
    def setUp(self):
        self.support = make_user("support_block", "support_block@example.com", is_support=True)
        self.staff = make_user("staff_block", "staff_block@example.com", is_staff=True)
        self.target = make_user("target_block", "target_block@example.com")

    def test_support_can_block_and_unblock_regular_user(self):
        self.client.force_authenticate(user=self.support)
        resp = self.client.post(f"/api/support/users/{self.target.id}/toggle-active/")
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

        resp = self.client.post(f"/api/support/users/{self.target.id}/toggle-active/")
        self.assertEqual(resp.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_cannot_block_self(self):
        self.client.force_authenticate(user=self.support)
        resp = self.client.post(f"/api/support/users/{self.support.id}/toggle-active/")
        self.assertEqual(resp.status_code, 400)

    def test_support_cannot_block_staff(self):
        self.client.force_authenticate(user=self.support)
        resp = self.client.post(f"/api/support/users/{self.staff.id}/toggle-active/")
        self.assertEqual(resp.status_code, 403)

    def test_staff_can_block_staff(self):
        other_staff = make_user("staff_block2", "staff_block2@example.com", is_staff=True)
        self.client.force_authenticate(user=self.staff)
        resp = self.client.post(f"/api/support/users/{other_staff.id}/toggle-active/")
        self.assertEqual(resp.status_code, 200)

    def test_blocked_user_cannot_login(self):
        """End-to-end: toggling a user off via the support dashboard must
        actually lock them out, the same way the existing is_active
        deactivation flow does."""
        self.client.force_authenticate(user=self.support)
        self.client.post(f"/api/support/users/{self.target.id}/toggle-active/")

        anon = self.client_class()
        resp = anon.post("/api/users/login/", {"email": "target_block@example.com", "password": "TestPass123!"})
        self.assertEqual(resp.status_code, 401)


class SupportGroupBrowsingTests(APITestCase):
    def setUp(self):
        self.support = make_user("support_group", "support_group@example.com", is_support=True)
        self.alice = make_user("alice_group", "alice_group@example.com")
        self.bob = make_user("bob_group", "bob_group@example.com")

        self.community = Community.objects.create(name="Support Group Community")
        Membership.objects.create(user=self.alice, community=self.community)
        Membership.objects.create(user=self.bob, community=self.community)

        self.circle = Circle.objects.create(name="Support Group Circle", created_by=self.alice)
        CircleMembership.objects.create(user=self.alice, circle=self.circle, role=CircleMembership.Role.OWNER)

        self.client.force_authenticate(user=self.support)

    def test_community_list_has_member_count(self):
        resp = self.client.get("/api/support/communities/")
        rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        match = next(r for r in rows if r["name"] == "Support Group Community")
        self.assertEqual(match["member_count"], 2)

    def test_community_members_endpoint(self):
        resp = self.client.get(f"/api/support/communities/{self.community.id}/members/")
        rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        usernames = {r["username"] for r in rows}
        self.assertEqual(usernames, {"alice_group", "bob_group"})

    def test_circle_members_endpoint(self):
        resp = self.client.get(f"/api/support/circles/{self.circle.id}/members/")
        rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "owner")


class SupportCommunityCreateDeleteTests(APITestCase):
    def setUp(self):
        self.support = make_user("support_cc", "support_cc@example.com", is_support=True)
        self.client.force_authenticate(user=self.support)

    def test_create_community(self):
        resp = self.client.post("/api/support/communities/", {"name": "New Support Community", "description": "made from the dashboard"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["name"], "New Support Community")
        self.assertEqual(resp.json()["member_count"], 1, "creator should be auto-joined")
        self.assertTrue(Community.objects.filter(name="New Support Community").exists())

    def test_create_community_without_staff_status(self):
        """Regression: the main POST /api/communities/ endpoint requires
        is_staff — a support-only (not staff) account must still be able
        to create communities through the dashboard's own endpoint."""
        self.assertFalse(self.support.is_staff)
        resp = self.client.post("/api/support/communities/", {"name": "Support-only creation"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_delete_community(self):
        community = Community.objects.create(name="To Delete")
        resp = self.client.delete(f"/api/support/communities/{community.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Community.objects.filter(id=community.id).exists())

    def test_remove_member_from_community(self):
        community = Community.objects.create(name="Remove Member Test")
        target = make_user("cc_member", "cc_member@example.com")
        Membership.objects.create(user=target, community=community)

        resp = self.client.delete(f"/api/support/communities/{community.id}/members/{target.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Membership.objects.filter(user=target, community=community).exists())

    def test_remove_member_not_in_community_404s(self):
        community = Community.objects.create(name="Empty Community")
        target = make_user("cc_not_member", "cc_not_member@example.com")
        resp = self.client.delete(f"/api/support/communities/{community.id}/members/{target.id}/")
        self.assertEqual(resp.status_code, 404)


class SupportCircleCreateDeleteTests(APITestCase):
    def setUp(self):
        self.support = make_user("support_circ_cc", "support_circ_cc@example.com", is_support=True)
        self.client.force_authenticate(user=self.support)

    def test_create_circle(self):
        resp = self.client.post("/api/support/circles/", {"name": "New Support Circle"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["member_count"], 1, "creator should be auto-joined as owner")
        self.assertTrue(Circle.objects.filter(name="New Support Circle").exists())

    def test_delete_circle(self):
        circle = Circle.objects.create(name="To Delete Circle", created_by=self.support)
        resp = self.client.delete(f"/api/support/circles/{circle.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Circle.objects.filter(id=circle.id).exists())

    def test_remove_member_from_circle(self):
        circle = Circle.objects.create(name="Remove Member Circle", created_by=self.support)
        target = make_user("circ_member", "circ_member@example.com")
        CircleMembership.objects.create(user=target, circle=circle)

        resp = self.client.delete(f"/api/support/circles/{circle.id}/members/{target.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CircleMembership.objects.filter(user=target, circle=circle).exists())


class SupportUserDetailTests(APITestCase):
    def setUp(self):
        self.support = make_user("support_detail", "support_detail@example.com", is_support=True)
        self.target = make_user("detail_target", "detail_target@example.com")
        self.client.force_authenticate(user=self.support)

    def test_user_detail_includes_communities_and_circles(self):
        community = Community.objects.create(name="Detail Test Community")
        Membership.objects.create(user=self.target, community=community, role=Membership.Role.ADMIN)
        circle = Circle.objects.create(name="Detail Test Circle", created_by=self.target)
        CircleMembership.objects.create(user=self.target, circle=circle, role=CircleMembership.Role.OWNER)

        resp = self.client.get(f"/api/support/users/{self.target.id}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["communities"]), 1)
        self.assertEqual(body["communities"][0]["name"], "Detail Test Community")
        self.assertEqual(len(body["circles"]), 1)
        self.assertEqual(body["circles"][0]["role"], "owner")


class SupportCommunityHoldTests(APITestCase):
    def setUp(self):
        self.support = make_user("support_hold", "support_hold@example.com", is_support=True)
        self.author = make_user("hold_author", "hold_author@example.com")
        self.community = Community.objects.create(name="Hold Test Community")
        Membership.objects.create(user=self.author, community=self.community)

    def test_toggle_hold(self):
        self.client.force_authenticate(user=self.support)
        resp = self.client.post(f"/api/support/communities/{self.community.id}/toggle-hold/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_on_hold"])

        resp = self.client.post(f"/api/support/communities/{self.community.id}/toggle-hold/")
        self.assertFalse(resp.json()["is_on_hold"])

    def test_cannot_post_while_on_hold(self):
        self.community.is_on_hold = True
        self.community.save(update_fields=["is_on_hold"])

        self.client.force_authenticate(user=self.author)
        resp = self.client.post("/api/posts/", {
            "post_type": "question", "title": "Can I post?", "body": "testing hold",
            "community": self.community.id,
        }, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_cannot_like_while_on_hold(self):
        from posts.models import Post
        post = Post.objects.create(
            community=self.community, author=self.author, post_type=Post.PostType.QUESTION,
            title="Q", body="body",
        )
        self.community.is_on_hold = True
        self.community.save(update_fields=["is_on_hold"])

        other = make_user("hold_liker", "hold_liker@example.com")
        Membership.objects.create(user=other, community=self.community)
        self.client.force_authenticate(user=other)
        resp = self.client.post(f"/api/posts/{post.id}/like/")
        self.assertEqual(resp.status_code, 403)

    def test_cannot_comment_while_on_hold(self):
        from posts.models import Post
        post = Post.objects.create(
            community=self.community, author=self.author, post_type=Post.PostType.QUESTION,
            title="Q", body="body",
        )
        self.community.is_on_hold = True
        self.community.save(update_fields=["is_on_hold"])

        self.client.force_authenticate(user=self.author)
        resp = self.client.post(f"/api/posts/{post.id}/comments/", {"body": "trying to comment"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_can_still_post_after_hold_lifted(self):
        self.community.is_on_hold = True
        self.community.save(update_fields=["is_on_hold"])
        self.community.is_on_hold = False
        self.community.save(update_fields=["is_on_hold"])

        self.client.force_authenticate(user=self.author)
        resp = self.client.post("/api/posts/", {
            "post_type": "question", "title": "Can I post now?", "body": "hold lifted",
            "community": self.community.id,
        }, format="json")
        self.assertEqual(resp.status_code, 201)


class SupportPostDeleteTests(APITestCase):
    def setUp(self):
        from posts.models import Post
        self.support = make_user("support_postdel", "support_postdel@example.com", is_support=True)
        self.author = make_user("postdel_author", "postdel_author@example.com")
        self.other = make_user("postdel_other", "postdel_other@example.com")
        community = Community.objects.create(name="Post Delete Test Community")
        Membership.objects.create(user=self.author, community=community)
        self.post = Post.objects.create(
            community=community, author=self.author, post_type=Post.PostType.QUESTION,
            title="Q", body="body",
        )

    def test_support_can_delete_any_post(self):
        from posts.models import Post
        self.client.force_authenticate(user=self.support)
        resp = self.client.delete(f"/api/support/posts/{self.post.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Post.objects.filter(id=self.post.id).exists())

    def test_regular_user_cannot_use_support_delete_endpoint(self):
        self.client.force_authenticate(user=self.other)
        resp = self.client.delete(f"/api/support/posts/{self.post.id}/")
        self.assertEqual(resp.status_code, 403)


class SupportTicketTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # each test gets a clean slate against the 3/min support_ticket throttle
        self.support = make_user("support_ticket", "support_ticket@example.com", is_support=True)

    def test_anyone_can_submit_a_ticket(self):
        resp = self.client.post("/api/support/tickets/create/", {
            "username": "blocked_person", "email": "blocked_person@example.com",
            "message": "My account got blocked and I don't know why.",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_ticket_without_message_rejected(self):
        resp = self.client.post("/api/support/tickets/create/", {
            "username": "someone", "message": "",
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_ticket_without_username_or_email_rejected(self):
        resp = self.client.post("/api/support/tickets/create/", {
            "message": "help me",
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_logged_in_user_ticket_is_linked_to_their_account(self):
        submitter = make_user("ticket_submitter", "ticket_submitter@example.com")
        self.client.force_authenticate(user=submitter)
        resp = self.client.post("/api/support/tickets/create/", {
            "username": "ticket_submitter", "message": "something's broken",
        }, format="json")
        self.assertEqual(resp.status_code, 201)

        self.client.force_authenticate(user=self.support)
        resp = self.client.get("/api/support/tickets/")
        rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        self.assertEqual(len(rows), 1)

    def test_regular_user_cannot_list_tickets(self):
        regular = make_user("ticket_regular", "ticket_regular@example.com")
        self.client.force_authenticate(user=regular)
        resp = self.client.get("/api/support/tickets/")
        self.assertEqual(resp.status_code, 403)

    def test_resolve_and_reopen_ticket(self):
        self.client.post("/api/support/tickets/create/", {"username": "x", "message": "help"}, format="json")
        self.client.force_authenticate(user=self.support)
        rows = self.client.get("/api/support/tickets/").json()
        rows = rows["results"] if isinstance(rows, dict) else rows
        ticket_id = rows[0]["id"]

        resp = self.client.post(f"/api/support/tickets/{ticket_id}/resolve/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "resolved")

        resp = self.client.post(f"/api/support/tickets/{ticket_id}/resolve/")
        self.assertEqual(resp.json()["status"], "open")

    def test_open_filter(self):
        self.client.post("/api/support/tickets/create/", {"username": "a", "message": "open one"}, format="json")
        self.client.post("/api/support/tickets/create/", {"username": "b", "message": "resolved one"}, format="json")
        self.client.force_authenticate(user=self.support)
        rows = self.client.get("/api/support/tickets/").json()
        rows = rows["results"] if isinstance(rows, dict) else rows
        to_resolve = next(r for r in rows if r["username"] == "b")
        self.client.post(f"/api/support/tickets/{to_resolve['id']}/resolve/")

        resp = self.client.get("/api/support/tickets/?status=open")
        open_rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(open_rows[0]["username"], "a")


class BlockedLoginMessageTests(APITestCase):
    def test_blocked_user_gets_clear_message(self):
        user = make_user("blocked_login", "blocked_login@example.com")
        user.is_active = False
        user.save(update_fields=["is_active"])

        resp = self.client.post("/api/users/login/", {"email": "blocked_login@example.com", "password": "TestPass123!"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("blocked", resp.json().get("detail", "").lower())

    def test_wrong_password_still_gets_generic_message_not_blocked_message(self):
        make_user("wrongpass_login", "wrongpass_login@example.com")
        resp = self.client.post("/api/users/login/", {"email": "wrongpass_login@example.com", "password": "WrongOne!"})
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("blocked", resp.json().get("detail", "").lower())
