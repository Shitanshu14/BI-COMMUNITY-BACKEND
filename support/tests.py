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
