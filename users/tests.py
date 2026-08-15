import base64

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

User = get_user_model()

# 1x1 transparent PNG — enough for Pillow to open/re-encode without needing
# a real test-fixture image file on disk.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class RegistrationTests(APITestCase):
    def test_register_success(self):
        resp = self.client.post("/api/users/register/", {
            "username": "newuser1", "email": "newuser1@example.com",
            "password": "TestPass123!", "role": "student",
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(User.objects.filter(email="newuser1@example.com").exists())

    def test_username_over_20_chars_rejected(self):
        """Regression: composer/register form caps usernames at 20 chars —
        the API must actually enforce it, not just the frontend maxLength."""
        resp = self.client.post("/api/users/register/", {
            "username": "thisusernameiswaytoolong", "email": "toolong@example.com",
            "password": "TestPass123!",
        })
        self.assertEqual(resp.status_code, 400)

    def test_username_under_3_chars_rejected(self):
        resp = self.client.post("/api/users/register/", {
            "username": "ab", "email": "short@example.com", "password": "TestPass123!",
        })
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username="existing", email="dupe@example.com", password="TestPass123!")
        resp = self.client.post("/api/users/register/", {
            "username": "different", "email": "dupe@example.com", "password": "TestPass123!",
        })
        self.assertEqual(resp.status_code, 400)


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="loginuser", email="login@example.com", password="TestPass123!")

    def test_login_success_sets_cookie(self):
        resp = self.client.post("/api/users/login/", {"email": "login@example.com", "password": "TestPass123!"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.cookies)

    def test_login_wrong_password_rejected(self):
        resp = self.client.post("/api/users/login/", {"email": "login@example.com", "password": "WrongPass!"})
        self.assertEqual(resp.status_code, 401)


class ProfileUpdateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="profileuser", email="profile@example.com", password="TestPass123!")
        self.client.force_authenticate(user=self.user)

    def test_headline_over_100_chars_rejected(self):
        resp = self.client.patch("/api/users/me/", {"headline": "x" * 101}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_bio_over_280_chars_rejected(self):
        resp = self.client.patch("/api/users/me/", {"bio": "y" * 281}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_valid_bio_and_headline_accepted(self):
        resp = self.client.patch("/api/users/me/", {"headline": "Student", "bio": "Hello world"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.bio, "Hello world")

    def test_username_change_over_limit_rejected(self):
        resp = self.client.patch("/api/users/me/", {"username": "waytoolongusernamehere"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_avatar_upload_is_compressed(self):
        """Regression: avatar/post-image uploads must be downscaled at
        write time (see setu_backend/imaging.py) — this proved a 4000x3000
        photo shrinks to <=1600px; here we just confirm the upload path
        round-trips successfully and a URL comes back."""
        avatar = SimpleUploadedFile("avatar.png", TINY_PNG, content_type="image/png")
        resp = self.client.patch("/api/users/me/", {"avatar": avatar}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json().get("avatar"))
