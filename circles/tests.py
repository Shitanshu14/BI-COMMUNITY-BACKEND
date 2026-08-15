from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Circle, CircleMembership

User = get_user_model()


def make_user(username, email):
    return User.objects.create_user(username=username, email=email, password="TestPass123!")


class CircleEventTests(APITestCase):
    def setUp(self):
        self.owner = make_user("circle_owner", "circle_owner@example.com")
        self.member = make_user("circle_member", "circle_member@example.com")
        self.outsider = make_user("circle_outsider", "circle_outsider@example.com")

        self.circle = Circle.objects.create(name="Test Circle", created_by=self.owner)
        CircleMembership.objects.create(user=self.owner, circle=self.circle, role=CircleMembership.Role.OWNER)
        CircleMembership.objects.create(user=self.member, circle=self.circle, role=CircleMembership.Role.MEMBER)

    def test_member_can_create_event(self):
        """Any member (not just the owner) can schedule an event — Circles
        are for equals collaborating, not a broadcast channel."""
        self.client.force_authenticate(user=self.member)
        resp = self.client.post(f"/api/circles/{self.circle.id}/events/", {
            "title": "Kickoff call", "starts_at": "2026-09-01T10:00:00Z", "location": "Zoom",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["my_rsvp"], "going", "creator should be auto-RSVP'd going")

    def test_outsider_cannot_view_or_create_events(self):
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(f"/api/circles/{self.circle.id}/events/")
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(f"/api/circles/{self.circle.id}/events/", {
            "title": "Crash the party", "starts_at": "2026-09-01T10:00:00Z",
        }, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_rsvp_flow_and_going_count(self):
        self.client.force_authenticate(user=self.owner)
        create_resp = self.client.post(f"/api/circles/{self.circle.id}/events/", {
            "title": "Weekly sync", "starts_at": "2026-09-01T10:00:00Z",
        }, format="json")
        event_id = create_resp.json()["id"]

        self.client.force_authenticate(user=self.member)
        rsvp_resp = self.client.post(f"/api/circles/{self.circle.id}/events/{event_id}/rsvp/", {"status": "maybe"}, format="json")
        self.assertEqual(rsvp_resp.status_code, 200)
        self.assertEqual(rsvp_resp.json()["going_count"], 1, "only the owner (auto-RSVP'd) should count as going")
        self.assertEqual(rsvp_resp.json()["my_rsvp"], "maybe")

    def test_only_creator_or_owner_can_delete_event(self):
        self.client.force_authenticate(user=self.member)
        create_resp = self.client.post(f"/api/circles/{self.circle.id}/events/", {
            "title": "Member's event", "starts_at": "2026-09-01T10:00:00Z",
        }, format="json")
        event_id = create_resp.json()["id"]

        second_member = make_user("circle_member2", "circle_member2@example.com")
        CircleMembership.objects.create(user=second_member, circle=self.circle, role=CircleMembership.Role.MEMBER)
        self.client.force_authenticate(user=second_member)
        resp = self.client.delete(f"/api/circles/{self.circle.id}/events/{event_id}/")
        self.assertEqual(resp.status_code, 403, "a member who didn't create the event and isn't owner shouldn't be able to delete it")

        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f"/api/circles/{self.circle.id}/events/{event_id}/")
        self.assertEqual(resp.status_code, 204, "circle owner should be able to delete any event")

    def test_invalid_rsvp_status_rejected(self):
        self.client.force_authenticate(user=self.owner)
        create_resp = self.client.post(f"/api/circles/{self.circle.id}/events/", {
            "title": "Event", "starts_at": "2026-09-01T10:00:00Z",
        }, format="json")
        event_id = create_resp.json()["id"]
        resp = self.client.post(f"/api/circles/{self.circle.id}/events/{event_id}/rsvp/", {"status": "definitely-not-a-real-status"}, format="json")
        self.assertEqual(resp.status_code, 400)
