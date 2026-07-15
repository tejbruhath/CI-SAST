"""Tenant isolation: a user can only ever see their own scans/findings.

Run: USE_SQLITE=1 python manage.py test tests.test_isolation
"""
from django.contrib.auth import get_user_model  # project User model
from rest_framework.test import APITestCase  # DRF APIClient-based tests

from sentriq.models import Scan, Finding  # resources under isolation

User = get_user_model()  # Django user class


class TenantIsolationTests(APITestCase):
    """Prove Alice's scans/findings are invisible to Bob (404, not 403)."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice")  # owner tenant
        self.bob = User.objects.create_user(username="bob")  # other tenant
        self.scan = Scan.objects.create(
            pipeline="static", target="git@x/repo", requested_by=self.alice)  # alice's scan
        self.finding = Finding.objects.create(
            scan=self.scan, tool="trivy", pipeline="static", type="vuln",
            severity="high", rule_id="R1", message="m", fingerprint="fp1")  # alice's finding

    def test_bob_cannot_see_alices_data(self):
        self.client.force_authenticate(self.bob)  # act as Bob

        # Lists are empty for a non-owner.
        self.assertEqual(self.client.get("/api/v1/scans").json(), [])  # no scans
        self.assertEqual(self.client.get("/api/v1/findings").json(), [])  # no findings

        # Direct access to another tenant's resource is 404, not 403.
        self.assertEqual(
            self.client.get(f"/api/v1/scans/{self.scan.id}").status_code, 404)  # hide existence
        self.assertEqual(
            self.client.get(f"/api/v1/findings/{self.finding.id}").status_code, 404)
        self.assertEqual(
            self.client.post(f"/api/v1/findings/{self.finding.id}/hitl",
                             {"action": "approve"}, format="json").status_code, 404)  # no write either

    def test_alice_sees_her_own_data(self):
        self.client.force_authenticate(self.alice)  # act as Alice
        self.assertEqual(len(self.client.get("/api/v1/scans").json()), 1)  # sees own scan
        self.assertEqual(
            self.client.get(f"/api/v1/scans/{self.scan.id}").status_code, 200)  # detail ok
