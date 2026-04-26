from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import patch

from runtime.models import BackendClaimAccount
from runtime.services.redis_runtime import (
    build_runtime_payload,
    list_connected_clients,
    list_token_pool_health,
)


class BackendClaimAccountTests(TestCase):
    def test_proxy_is_optional(self):
        account = BackendClaimAccount(
            label="acc-1",
            username="tester",
            cookies_json='[{"name":"cf_clearance","value":"abc"}]',
            x_access_token="token-1",
            user_agent="Mozilla/5.0",
            proxy_url="",
            is_enabled=False,
            is_active=True,
        )

        account.full_clean()

    def test_blank_access_token_is_rejected(self):
        account = BackendClaimAccount(
            label="acc-2",
            username="tester-2",
            cookies_json="[]",
            x_access_token="",
            user_agent="Mozilla/5.0",
        )

        with self.assertRaises(ValidationError):
            account.full_clean()


class RuntimeSyncTests(TestCase):
    def test_runtime_payload_contains_optional_proxy_field(self):
        account = BackendClaimAccount.objects.create(
            label="acc-sync",
            username="runtime-user",
            cookies_json="[]",
            x_access_token="token-sync",
            user_agent="Mozilla/5.0",
            proxy_url="",
            is_enabled=True,
        )

        payload = build_runtime_payload(account)

        self.assertEqual(payload["account_id"], account.id)
        self.assertEqual(payload["proxy_url"], "")

    @patch("runtime.services.redis_runtime.get_redis_client")
    def test_sync_enabled_account_writes_hash_and_set(self, client_factory):
        fake = client_factory.return_value
        account = BackendClaimAccount.objects.create(
            label="acc-enabled",
            username="enabled-user",
            cookies_json="[]",
            x_access_token="token-enabled",
            user_agent="Mozilla/5.0",
            is_enabled=True,
        )

        from runtime.services.redis_runtime import sync_account_to_runtime

        sync_account_to_runtime(account)

        fake.set.assert_called_once()
        fake.sadd.assert_called_once_with("runtime:accounts:enabled", str(account.id))
        fake.publish.assert_called_once()

    @patch("runtime.services.redis_runtime.get_redis_client")
    def test_list_connected_clients_reads_presence_payloads(self, client_factory):
        fake = client_factory.return_value
        fake.smembers.return_value = {"ws-2", "ws-1"}
        fake.get.side_effect = [
            '{"client_id":"ws-1","remote_ip":"1.1.1.1","user_agent":"UA 1","last_seen_at":"2026-04-21T00:00:00Z"}',
            '{"client_id":"ws-2","remote_ip":"2.2.2.2","user_agent":"UA 2","last_seen_at":"2026-04-21T00:00:01Z"}',
        ]

        clients = list_connected_clients()

        self.assertEqual([client["client_id"] for client in clients], ["ws-1", "ws-2"])

    @patch("runtime.services.redis_runtime.get_redis_client")
    def test_list_token_pool_health_uses_runtime_meta(self, client_factory):
        fake = client_factory.return_value
        fake.get.side_effect = [
            '{"available_tokens":2,"target_tokens":2,"updated_at":"2026-04-21T01:02:03Z"}'
        ]
        account = BackendClaimAccount.objects.create(
            label="acc-health",
            username="health-user",
            cookies_json="[]",
            x_access_token="token-health",
            user_agent="Mozilla/5.0",
            is_enabled=True,
        )

        health = list_token_pool_health([account])

        self.assertEqual(health[0]["available_tokens"], 2)
        self.assertEqual(health[0]["label"], "acc-health")


class RuntimeDashboardViewTests(TestCase):
    @patch("runtime.views.list_token_pool_health")
    @patch("runtime.views.list_connected_clients")
    def test_runtime_dashboard_requires_login(self, connected_clients, token_health):
        response = self.client.get("/runtime/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    @patch("runtime.views.list_token_pool_health")
    @patch("runtime.views.list_connected_clients")
    def test_runtime_dashboard_renders_runtime_data(self, connected_clients, token_health):
        User = get_user_model()
        user = User.objects.create_user(username="admin", password="pass12345")
        self.client.force_login(user)
        BackendClaimAccount.objects.create(
            label="acc-dashboard",
            username="dashboard-user",
            cookies_json="[]",
            x_access_token="token-dashboard",
            user_agent="Mozilla/5.0",
            is_enabled=True,
        )
        connected_clients.return_value = [
            {"client_id": "ws-1", "remote_ip": "1.1.1.1", "user_agent": "UA", "last_seen_at": "now"}
        ]
        token_health.return_value = [
            {
                "label": "acc-dashboard",
                "username": "dashboard-user",
                "is_enabled": True,
                "available_tokens": 2,
                "target_tokens": 2,
                "updated_at": "now",
            }
        ]

        response = self.client.get("/runtime/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Runtime Dashboard")
        self.assertContains(response, "ws-1")
        self.assertContains(response, "acc-dashboard")
