"""Tests for Sentriq session/auth hardening."""
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from sentriq import crypto
from sentriq.models import UserProfile

User = get_user_model()


class AuthTests(TestCase):
    def setUp(self):
        # Tests need a working encryption key but must not depend on env.
        if not crypto._token_key:
            crypto._token_key = Fernet.generate_key().decode()

        self.client = Client()
        self.user = User.objects.create_user(username="testuser")
        self.profile = UserProfile.objects.create(
            user=self.user,
            github_id="123",
            github_login="testlogin",
            github_access_token=crypto.encrypt_token("gho_fake_token"),
        )

    def test_unauthenticated_findings_returns_401(self):
        """The SPA expects 401 so it can detect logged-out state."""
        response = self.client.get("/api/v1/findings")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Authentication credentials were not provided.")

    def test_logout_revokes_token_and_kills_session(self):
        """Logout revokes the GitHub token, blanks it, and clears the session."""
        self.client.force_login(self.user)

        with (
            patch("sentriq.github.GITHUB_CLIENT_ID", "test_client_id"),
            patch("sentriq.github.GITHUB_CLIENT_SECRET", "test_secret"),
            patch("sentriq.github.httpx.request") as mock_request,
        ):
            mock_request.return_value = Mock(status_code=204, text="")
            response = self.client.post("/api/v1/auth/logout")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "logged_out")

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.github_access_token, "")

        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "DELETE")
        self.assertIn("/applications/test_client_id/grant", args[1])
        self.assertEqual(kwargs["auth"], ("test_client_id", "test_secret"))
        self.assertEqual(kwargs["json"], {"access_token": "gho_fake_token"})

        # Session must be gone.
        me_response = self.client.get("/api/v1/auth/me")
        self.assertEqual(me_response.status_code, 401)

    def test_logout_survives_revoke_failure(self):
        """A failure to contact GitHub must not prevent logout."""
        self.client.force_login(self.user)

        with (
            patch("sentriq.github.GITHUB_CLIENT_ID", "test_client_id"),
            patch("sentriq.github.GITHUB_CLIENT_SECRET", "test_secret"),
            patch("sentriq.github.httpx.request", side_effect=Exception("network down")),
        ):
            response = self.client.post("/api/v1/auth/logout")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "logged_out")

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.github_access_token, "")
