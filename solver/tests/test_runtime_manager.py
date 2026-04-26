import json
import unittest
from datetime import datetime, timedelta, timezone

from src.runtime_manager import RuntimeAccount, RuntimeAccountManager


class FakeRedis:
    def __init__(self):
        self.strings = {}
        self.sets = {}
        self.lists = {}
        self.published = []

    async def smembers(self, key):
        return self.sets.get(key, set()).copy()

    async def get(self, key):
        return self.strings.get(key)

    async def set(self, key, value, *args, **kwargs):
        self.strings[key] = value

    async def delete(self, *keys):
        for key in keys:
            self.strings.pop(key, None)
            self.lists.pop(key, None)

    async def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)

    async def srem(self, key, *values):
        current = self.sets.setdefault(key, set())
        for value in values:
            current.discard(value)

    async def publish(self, channel, payload):
        self.published.append((channel, payload))

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        if end == -1:
            return values[start:]
        return values[start : end + 1]

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)


class RuntimeAccountManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_enabled_accounts_reads_runtime_cache(self):
        fake_redis = FakeRedis()
        fake_redis.sets["runtime:accounts:enabled"] = {"7"}
        fake_redis.strings["runtime:account:7"] = json.dumps(
            {
                "account_id": 7,
                "label": "alpha",
                "username": "alice",
                "cookies_json": "[]",
                "x_access_token": "token",
                "user_agent": "Mozilla/5.0",
                "proxy_url": "",
                "is_enabled": True,
                "is_active": True,
            }
        )

        manager = RuntimeAccountManager(
            redis_client=fake_redis,
            solver_func=self._solver_factory(["tok-1", "tok-2"]),
            target_tokens=2,
            maintain_interval_seconds=0.01,
        )

        await manager.load_enabled_accounts()

        self.assertIn(7, manager.accounts)
        self.assertEqual(manager.accounts[7].label, "alpha")

    async def test_reconcile_account_refills_missing_tokens_and_updates_meta(self):
        fake_redis = FakeRedis()
        manager = RuntimeAccountManager(
            redis_client=fake_redis,
            solver_func=self._solver_factory(["tok-a", "tok-b"]),
            target_tokens=2,
            maintain_interval_seconds=0.01,
        )
        manager.accounts[9] = self._account(9)

        await manager.reconcile_account(9)

        self.assertEqual(len(fake_redis.lists["runtime:tokens:9"]), 2)
        meta = json.loads(fake_redis.strings["runtime:tokens:meta:9"])
        self.assertEqual(meta["available_tokens"], 2)
        self.assertEqual(meta["account_id"], 9)

    async def test_reconcile_account_discards_expired_tokens(self):
        fake_redis = FakeRedis()
        now = datetime.now(timezone.utc)
        fake_redis.lists["runtime:tokens:11"] = [
            json.dumps(
                {
                    "token": "expired",
                    "created_at": (now - timedelta(minutes=2)).isoformat(),
                    "expires_at": (now - timedelta(seconds=5)).isoformat(),
                }
            ),
            json.dumps(
                {
                    "token": "still-good",
                    "created_at": (now - timedelta(seconds=5)).isoformat(),
                    "expires_at": (now + timedelta(seconds=60)).isoformat(),
                }
            ),
        ]
        manager = RuntimeAccountManager(
            redis_client=fake_redis,
            solver_func=self._solver_factory(["fresh-token"]),
            target_tokens=2,
            maintain_interval_seconds=0.01,
        )
        manager.accounts[11] = self._account(11)

        await manager.reconcile_account(11)

        stored = [json.loads(item)["token"] for item in fake_redis.lists["runtime:tokens:11"]]
        self.assertEqual(stored, ["still-good", "fresh-token"])

    async def test_disable_account_clears_runtime_keys(self):
        fake_redis = FakeRedis()
        fake_redis.sets["runtime:accounts:enabled"] = {"13"}
        fake_redis.strings["runtime:account:13"] = json.dumps({"account_id": 13})
        fake_redis.lists["runtime:tokens:13"] = ["token-payload"]
        fake_redis.strings["runtime:tokens:meta:13"] = json.dumps({"available_tokens": 1})

        manager = RuntimeAccountManager(
            redis_client=fake_redis,
            solver_func=self._solver_factory(["unused"]),
            target_tokens=2,
            maintain_interval_seconds=0.01,
        )
        manager.accounts[13] = self._account(13)

        await manager.disable_account(13)

        self.assertNotIn("13", fake_redis.sets["runtime:accounts:enabled"])
        self.assertNotIn("runtime:tokens:13", fake_redis.lists)
        self.assertNotIn("runtime:tokens:meta:13", fake_redis.strings)
        self.assertTrue(any(channel == "events:accounts" for channel, _ in fake_redis.published))

    def _solver_factory(self, values):
        tokens = iter(values)

        async def solve(account):
            return next(tokens)

        return solve

    def _account(self, account_id):
        return RuntimeAccount(
            account_id=account_id,
            label=f"acc-{account_id}",
            username=f"user-{account_id}",
            cookies_json="[]",
            x_access_token=f"token-{account_id}",
            user_agent="Mozilla/5.0",
            proxy_url="",
            is_enabled=True,
            is_active=True,
        )


if __name__ == "__main__":
    unittest.main()
