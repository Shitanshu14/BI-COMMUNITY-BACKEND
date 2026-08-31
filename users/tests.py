import base64

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

User = get_user_model()

# Bypass throttling in tests since DRF caches api_settings at startup
from users.views import (
    RegisterView, CookieTokenObtainPairView, PasswordResetRequestView,
    PasswordResetConfirmView, ConfirmEmailView, ResendVerificationEmailView
)
RegisterView.throttle_classes = []
CookieTokenObtainPairView.throttle_classes = []
PasswordResetRequestView.throttle_classes = []
PasswordResetConfirmView.throttle_classes = []
ConfirmEmailView.throttle_classes = []
ResendVerificationEmailView.throttle_classes = []

# 1x1 transparent PNG — enough for Pillow to open/re-encode without needing
# a real test-fixture image file on disk.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@override_settings(REST_FRAMEWORK={
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {},
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'users.authentication.CookieJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
})
class RegistrationTests(APITestCase):
    def test_register_success(self):
        resp = self.client.post("/api/users/register/", {
            "username": "newuser1", "email": "newuser1@example.com",
            "password": "TestPass123!", "role": "student",
            "first_name": "New", "last_name": "User",
            "date_of_birth": "2012-01-01", # Age 14 (student under 18)
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(User.objects.filter(email="newuser1@example.com").exists())

    def test_username_over_20_chars_rejected(self):
        """Regression: composer/register form caps usernames at 20 chars —
        the API must actually enforce it, not just the frontend maxLength."""
        resp = self.client.post("/api/users/register/", {
            "username": "thisusernameiswaytoolong", "email": "toolong@example.com",
            "password": "TestPass123!",
            "first_name": "New", "last_name": "User",
            "date_of_birth": "2012-01-01",
        })
        self.assertEqual(resp.status_code, 400)

    def test_username_under_3_chars_rejected(self):
        resp = self.client.post("/api/users/register/", {
            "username": "ab", "email": "short@example.com", "password": "TestPass123!",
            "first_name": "New", "last_name": "User",
            "date_of_birth": "2012-01-01",
        })
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username="existing", email="dupe@example.com", password="TestPass123!")
        resp = self.client.post("/api/users/register/", {
            "username": "different", "email": "dupe@example.com", "password": "TestPass123!",
            "first_name": "New", "last_name": "User",
            "date_of_birth": "2012-01-01",
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


@override_settings(REST_FRAMEWORK={
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {},
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'users.authentication.CookieJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
})
class NewFeatureValidationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="TestPass123!",
            first_name="Test",
            last_name="User",
            date_of_birth="2000-01-01"
        )
        from users.models import PasswordHistory
        PasswordHistory.objects.create(user=self.user, password_hash=self.user.password)

    def test_student_age_gate_under_18_passes(self):
        resp = self.client.post("/api/users/register/", {
            "username": "stud1", "email": "stud1@example.com",
            "password": "TestPass123!", "role": "student",
            "first_name": "Stud", "last_name": "One",
            "date_of_birth": "2015-05-05" # Under 18
        })
        self.assertEqual(resp.status_code, 201)

    def test_student_age_gate_over_18_fails(self):
        resp = self.client.post("/api/users/register/", {
            "username": "stud2", "email": "stud2@example.com",
            "password": "TestPass123!", "role": "student",
            "first_name": "Stud", "last_name": "Two",
            "date_of_birth": "2000-05-05" # Over 18
        })
        self.assertEqual(resp.status_code, 400)

    def test_professional_age_gate_under_18_fails(self):
        resp = self.client.post("/api/users/register/", {
            "username": "prof1", "email": "prof1@example.com",
            "password": "TestPass123!", "role": "professional",
            "first_name": "Prof", "last_name": "One",
            "date_of_birth": "2015-05-05" # Under 18
        })
        self.assertEqual(resp.status_code, 400)

    def test_professional_age_gate_over_18_passes(self):
        resp = self.client.post("/api/users/register/", {
            "username": "prof2", "email": "prof2@example.com",
            "password": "TestPass123!", "role": "professional",
            "first_name": "Prof", "last_name": "Two",
            "date_of_birth": "1998-05-05" # Over 18
        })
        self.assertEqual(resp.status_code, 201)

    def test_password_strength_validator_rejects_missing_symbol(self):
        resp = self.client.post("/api/users/register/", {
            "username": "pass1", "email": "pass1@example.com",
            "password": "TestPassWithoutSymbol1", "role": "student",
            "first_name": "Pass", "last_name": "One",
            "date_of_birth": "2015-05-05"
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("symbol", str(resp.content))

    def test_password_strength_validator_rejects_few_unique_chars(self):
        resp = self.client.post("/api/users/register/", {
            "username": "pass2", "email": "pass2@example.com",
            "password": "aaaaaaa!", "role": "student",
            "first_name": "Pass", "last_name": "Two",
            "date_of_birth": "2015-05-05"
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("unique", str(resp.content))

    def test_multi_identifier_login(self):
        # Login using email
        resp1 = self.client.post("/api/users/login/", {"email": "testuser@example.com", "password": "TestPass123!"})
        self.assertEqual(resp1.status_code, 200)

        # Login using username in the email field
        resp2 = self.client.post("/api/users/login/", {"email": "testuser", "password": "TestPass123!"})
        self.assertEqual(resp2.status_code, 200)

    def test_deactivate_account_success(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post("/api/users/deactivate/", {"username": "testuser", "password": "TestPass123!"})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_deactivate_account_invalid_username_fails(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post("/api/users/deactivate/", {"username": "wronguser", "password": "TestPass123!"})
        self.assertEqual(resp.status_code, 400)

    def test_password_history_prevent_reuse(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        # Attempt to reset password to the current password (TestPass123!)
        resp = self.client.post("/api/users/password/reset/confirm/", {
            "uid": uid,
            "token": token,
            "new_password": "TestPass123!"
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("reuse", str(resp.content))
