import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, Optional


logger = logging.getLogger(__name__)


@dataclass
class RuntimeAccount:
    account_id: int
    label: str
    username: str
    cookies_json: str
    x_access_token: str
    user_agent: str
    proxy_url: str
    is_enabled: bool
    is_active: bool


@dataclass
class TokenPayload:
    token: str
    created_at: datetime
    expires_at: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "token": self.token,
                "created_at": self.created_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "TokenPayload":
        payload = json.loads(raw)
        return cls(
            token=payload["token"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
        )


class RuntimeAccountManager:
    def __init__(
        self,
        redis_client,
        solver_func: Callable[[RuntimeAccount], Awaitable[str]],
        target_tokens: int = 2,
        token_ttl_seconds: int = 90,
        refresh_margin_seconds: int = 20,
        maintain_interval_seconds: float = 5.0,
    ):
        self.redis_client = redis_client
        self.solver_func = solver_func
        self.target_tokens = target_tokens
        self.token_ttl_seconds = token_ttl_seconds
        self.refresh_margin_seconds = refresh_margin_seconds
        self.maintain_interval_seconds = maintain_interval_seconds
        self.accounts: Dict[int, RuntimeAccount] = {}
        self._tasks: Dict[int, asyncio.Task] = {}

    async def load_enabled_accounts(self) -> None:
        account_ids = await self.redis_client.smembers("runtime:accounts:enabled")
        for raw_account_id in account_ids:
            account_id = int(raw_account_id)
            account = await self.fetch_account(account_id)
            if account:
                await self.enable_account(account)

    async def fetch_account(self, account_id: int) -> Optional[RuntimeAccount]:
        payload = await self.redis_client.get(f"runtime:account:{account_id}")
        if not payload:
            return None
        data = json.loads(payload)
        return RuntimeAccount(
            account_id=int(data["account_id"]),
            label=data["label"],
            username=data["username"],
            cookies_json=data["cookies_json"],
            x_access_token=data["x_access_token"],
            user_agent=data["user_agent"],
            proxy_url=data.get("proxy_url", ""),
            is_enabled=bool(data["is_enabled"]),
            is_active=bool(data["is_active"]),
        )

    async def enable_account(self, account: RuntimeAccount) -> None:
        self.accounts[account.account_id] = account
        await self.redis_client.sadd("runtime:accounts:enabled", str(account.account_id))
        await self.redis_client.set(
            f"runtime:account:{account.account_id}",
            json.dumps(
                {
                    "account_id": account.account_id,
                    "label": account.label,
                    "username": account.username,
                    "cookies_json": account.cookies_json,
                    "x_access_token": account.x_access_token,
                    "user_agent": account.user_agent,
                    "proxy_url": account.proxy_url,
                    "is_enabled": account.is_enabled,
                    "is_active": account.is_active,
                }
            ),
        )
        await self.redis_client.publish(
            "events:accounts",
            json.dumps({"type": "account_enabled", "account_id": account.account_id}),
        )
        self._ensure_task(account.account_id)

    async def disable_account(self, account_id: int) -> None:
        self.accounts.pop(account_id, None)
        task = self._tasks.pop(account_id, None)
        if task:
            task.cancel()
        await self.redis_client.srem("runtime:accounts:enabled", str(account_id))
        await self.redis_client.delete(
            f"runtime:account:{account_id}",
            f"runtime:tokens:{account_id}",
            f"runtime:tokens:meta:{account_id}",
        )
        await self.redis_client.publish(
            "events:accounts",
            json.dumps({"type": "account_disabled", "account_id": account_id}),
        )

    async def handle_account_event(self, raw_payload: str) -> None:
        payload = json.loads(raw_payload)
        account_id = int(payload["account_id"])
        event_type = payload["type"]
        if event_type == "account_disabled":
            await self.disable_account(account_id)
            return

        account = await self.fetch_account(account_id)
        if account is None:
            logger.warning("Runtime account %s missing during %s event", account_id, event_type)
            return

        self.accounts[account.account_id] = account
        self._ensure_task(account.account_id)

    async def run_event_listener(self, pubsub) -> None:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            await self.handle_account_event(message["data"])

    def _ensure_task(self, account_id: int) -> None:
        existing = self._tasks.get(account_id)
        if existing and not existing.done():
            return
        self._tasks[account_id] = asyncio.create_task(self._maintain_account(account_id))

    async def _maintain_account(self, account_id: int) -> None:
        while account_id in self.accounts:
            try:
                await self.reconcile_account(account_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Failed to reconcile token pool for %s: %s", account_id, exc)
            await asyncio.sleep(self.maintain_interval_seconds)

    async def reconcile_account(self, account_id: int) -> None:
        account = self.accounts.get(account_id)
        if not account:
            return

        valid_tokens = await self._load_valid_tokens(account_id)
        missing = self.target_tokens - len(valid_tokens)

        for _ in range(max(missing, 0)):
            token = await self.solver_func(account)
            now = datetime.now(timezone.utc)
            valid_tokens.append(
                TokenPayload(
                    token=token,
                    created_at=now,
                    expires_at=now + timedelta(seconds=self.token_ttl_seconds),
                )
            )

        await self.redis_client.delete(f"runtime:tokens:{account_id}")
        if valid_tokens:
            await self.redis_client.rpush(
                f"runtime:tokens:{account_id}",
                *[token.to_json() for token in valid_tokens],
            )

        await self.redis_client.set(
            f"runtime:tokens:meta:{account_id}",
            json.dumps(
                {
                    "account_id": account_id,
                    "available_tokens": len(valid_tokens),
                    "target_tokens": self.target_tokens,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )

    async def _load_valid_tokens(self, account_id: int) -> list[TokenPayload]:
        raw_tokens = await self.redis_client.lrange(f"runtime:tokens:{account_id}", 0, -1)
        now = datetime.now(timezone.utc)
        valid_tokens = []
        for raw in raw_tokens:
            token = TokenPayload.from_json(raw)
            if token.expires_at <= now + timedelta(seconds=self.refresh_margin_seconds):
                continue
            valid_tokens.append(token)
        return valid_tokens
