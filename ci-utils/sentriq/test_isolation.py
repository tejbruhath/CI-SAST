"""Tenant isolation: a user can only ever see their own scans/findings.

Run: USE_SQLITE=1 python manage.py test sentriq.test_isolation
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Scan, Finding

User = get_user_model()


class TenantIsolationTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice")
        self.bob = User.objects.create_user(username="bob")
        self.scan = Scan.objects.create(
            pipeline="static", target="git@x/repo", requested_by=self.alice)
        self.finding = Finding.objects.create(
            scan=self.scan, tool="trivy", pipeline="static", type="vuln",
            severity="high", rule_id="R1", message="m", fingerprint="fp1")

    def test_bob_cannot_see_alices_data(self):
        self.client.force_authenticate(self.bob)

        # Lists are empty for a non-owner.
        self.assertEqual(self.client.get("/api/v1/scans").json(), [])
        self.assertEqual(self.client.get("/api/v1/findings").json(), [])

        # Direct access to another tenant's resource is 404, not 403.
        self.assertEqual(
            self.client.get(f"/api/v1/scans/{self.scan.id}").status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/v1/findings/{self.finding.id}").status_code, 404)
        self.assertEqual(
            self.client.post(f"/api/v1/findings/{self.finding.id}/hitl",
                             {"action": "approve"}, format="json").status_code, 404)

    def test_alice_sees_her_own_data(self):
        self.client.force_authenticate(self.alice)
        self.assertEqual(len(self.client.get("/api/v1/scans").json()), 1)
        self.assertEqual(
            self.client.get(f"/api/v1/scans/{self.scan.id}").status_code, 200)
