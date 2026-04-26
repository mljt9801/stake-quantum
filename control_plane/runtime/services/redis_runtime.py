import json

import redis
from django.conf import settings


def get_redis_client():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def account_runtime_key(account_id: int) -> str:
    return f"runtime:account:{account_id}"


def client_presence_key(client_id: str) -> str:
    return f"runtime:client:{client_id}"


def token_pool_key(account_id: int) -> str:
    return f"runtime:tokens:{account_id}"


def token_pool_meta_key(account_id: int) -> str:
    return f"runtime:tokens:meta:{account_id}"


def build_runtime_payload(account):
    return {
        "account_id": account.id,
        "label": account.label,
        "username": account.username,
        "cookies_json": account.cookies_json,
        "x_access_token": account.x_access_token,
        "user_agent": account.user_agent,
        "proxy_url": account.proxy_url or "",
        "is_enabled": account.is_enabled,
        "is_active": account.is_active,
    }


def _parse_json_payload(raw_payload):
    if not raw_payload:
        return None
    return json.loads(raw_payload)


def list_connected_clients():
    client = get_redis_client()
    connected_ids = sorted(client.smembers("runtime:clients:connected"))
    clients = []
    for client_id in connected_ids:
        payload = _parse_json_payload(client.get(client_presence_key(client_id)))
        if payload:
            clients.append(payload)
    return clients


def list_token_pool_health(accounts):
    client = get_redis_client()
    token_health = []
    for account in accounts:
        meta = _parse_json_payload(client.get(token_pool_meta_key(account.id))) or {}
        token_health.append(
            {
                "account_id": account.id,
                "label": account.label,
                "username": account.username,
                "is_enabled": account.is_enabled,
                "available_tokens": meta.get("available_tokens", 0),
                "target_tokens": meta.get("target_tokens", 0),
                "updated_at": meta.get("updated_at", ""),
            }
        )
    return token_health


def sync_account_to_runtime(account) -> None:
    client = get_redis_client()
    payload = json.dumps(build_runtime_payload(account))
    client.set(account_runtime_key(account.id), payload)
    client.sadd("runtime:accounts:enabled", str(account.id))
    client.publish(
        "events:accounts",
        json.dumps({"type": "account_enabled", "account_id": account.id}),
    )


def remove_account_from_runtime(account_id: int) -> None:
    client = get_redis_client()
    client.delete(account_runtime_key(account_id))
    client.srem("runtime:accounts:enabled", str(account_id))
    client.delete(token_pool_key(account_id))
    client.delete(token_pool_meta_key(account_id))
    client.publish(
        "events:accounts",
        json.dumps({"type": "account_disabled", "account_id": account_id}),
    )
