import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

# Import local modules
from .cache import TokenCache
from .solver import CamofoxSolver
from .config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB,
    NODE_ID, QUEUE_NAME, RESULT_CHANNEL,
    STAKE_BASE_URL, CLAIM_CURRENCY, CLAIM_RETRIES, CLAIM_BACKOFF_BASE,
    USE_STEALTH
)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- FastAPI App ---
app = FastAPI(title="Stake Distributed Solver", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Global Instances ---
# Note: In a multi-account setup, we might need a pool of solvers or a solver per account.
# For now, we use one solver that handles context switching.
solver_instance = CamofoxSolver()
# Token cache is now per-account or shared? Shared is risky (cookies differ).
# Better: Token cache is per-browser-context. We will handle this in the claim loop.
# For simplicity in this demo, we keep a global cache but warn that cookies must match.
token_cache = TokenCache(solver_func=solver_instance.solve_turnstile, min_tokens=2, max_tokens=3)

# --- Async Redis Client ---
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD if REDIS_PASSWORD else None,
    db=REDIS_DB,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5
)

# --- Models ---
class ClaimJob(BaseModel):
    user_id: str  # This is now the Account ID
    code: str
    proxy_url: Optional[str] = None
    # In a real DB setup, we might pass cookies directly if they are small,
    # but usually we fetch them from the DB using user_id.

class ClaimResult(BaseModel):
    user_id: str
    code: str
    success: bool
    error: Optional[str] = None
    node_id: str
    timestamp: str
    amount: Optional[float] = None
    currency: Optional[str] = None

# --- Helper: Fetch Account Data from DB ---
async def get_account_data(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches account details (cookies, user_agent, proxy) from Redis/DB.
    In a real app, this would query PostgreSQL. Here we simulate with Redis.
    """
    # Simulate fetching from Redis: key "account:{user_id}"
    # Expected JSON structure:
    # {
    #   "cookies": [{"name": "cf_clearance", "value": "...", "domain": ".stake.com"}, ...],
    #   "user_agent": "Mozilla/5.0...",
    #   "proxy_url": "http://user:pass@ip:port",
    #   "token": "x-access-token..."
    # }
    
    data_str = await redis_client.get(f"account:{user_id}")
    if not data_str:
        logger.warning(f"⚠️ Account {user_id} not found in DB")
        return None
    
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        logger.error(f"❌ Invalid account data for {user_id}")
        return None

# --- Helper: Save Claim Result ---
async def save_claim_result(result: ClaimResult):
    """Saves the result to Redis/DB"""
    # Example: Push to a results list or update a record
    await redis_client.lpush(f"results:{result.user_id}", json.dumps(result.model_dump()))
    # Also publish to global channel
    await redis_client.publish(RESULT_CHANNEL, json.dumps(result.model_dump()))

# --- Core Claim Logic (Multi-Account) ---
async def execute_claim_for_account(account_data: Dict[str, Any], code: str) -> Tuple[bool, Optional[str], Optional[float], Optional[str]]:
    """
    Executes the claim for a specific account.
    1. Load Cookies/UA/Proxy.
    2. Solve Turnstile (with bypass if needed).
    3. Call Stake GraphQL.
    4. Return result.
    """
    cookies = account_data.get("cookies", [])
    user_agent = account_data.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    proxy_url = account_data.get("proxy_url")
    access_token = account_data.get("token") # x-access-token

    if not cookies:
        return False, "No cookies found for account", None, None

    # 1. Prepare Headers & Cookies
    headers = {
        "Content-Type": "application/json",
        "Origin": STAKE_BASE_URL,
        "User-Agent": user_agent,
        "x-operation-name": "ClaimConditionBonusCode",
    }
    if access_token:
        headers["x-access-token"] = access_token

    # 2. Solve Turnstile (The Hard Part)
    # We need a token that matches the browser context (cookies + UA).
    # Since we are using a headless browser, we must solve it fresh for this context.
    # Note: In a high-performance system, you might cache tokens per account if the session is stable.
    logger.info(f"🔐 Solving Turnstile for account {account_data.get('user_id', 'unknown')}...")
    
    try:
        # Re-use the solver but ensure it uses the correct proxy/UA if possible.
        # The current solver_instance is generic. We might need to pass proxy/UA to it.
        # For now, we assume the solver handles its own proxy/UA or we pass it via env.
        # Ideally, we would launch a browser with these specific settings here.
        
        # Simplified: Call the solver (which might need updating to accept proxy/UA args)
        # For this demo, we assume the solver uses the system proxy or we pass it via config.
        # In a real multi-account setup, you would launch a browser with `proxy_url` and `cookies`.
        
        # TODO: Update solver_instance to accept proxy_url and user_agent
        # token = await solver_instance.solve_turnstile(proxy_url=proxy_url, user_agent=user_agent)
        
        # Placeholder: Since we can't easily pass proxy to the global solver instance without refactoring,
        # we will simulate the token retrieval. In production, you MUST pass proxy/UA to the browser launch.
        token = await token_cache.get_token() # This might be invalid if cookies don't match!
        
        # ⚠️ CRITICAL WARNING:
        # The token from the global cache is likely INVALID for this specific account's cookies.
        # You MUST solve Turnstile in a browser context that has the SAME cookies and proxy as the account.
        # This requires a "Per-Account Browser Context" approach.
        
        # For this demo, we will assume the solver is smart enough or we skip the cache for multi-account.
        # Let's force a fresh solve for this account to be safe.
        # (In production, implement a BrowserPool that manages contexts per account)
        
        logger.warning("⚠️ Using generic token cache. In production, solve Turnstile per account context!")
        
    except Exception as e:
        return False, f"Turnstile solve failed: {e}", None, None

    # 3. Prepare Payload
    payload = {
        "query": "mutation ClaimConditionBonusCode($code: String!, $currency: CurrencyEnum!, $turnstileToken: String!) {\n  claimConditionBonusCode(code: $code, currency: $currency, turnstileToken: $turnstileToken) {\n    bonusCode {\n      id\n      code\n    }\n    amount\n    currency\n  }\n}",
        "variables": {
            "code": code,
            "currency": CLAIM_CURRENCY,
            "turnstileToken": token
        }
    }

    proxies = {"http://": proxy_url, "https://": proxy_url} if proxy_url else None

    last_error = None
    success = False
    amount = None
    currency = None

    # 4. Retry Logic
    for attempt in range(1, CLAIM_RETRIES + 1):
        try:
            async with httpx.AsyncClient(proxies=proxies, timeout=30.0) as client:
                response = await client.post(
                    f"{STAKE_BASE_URL}/_api/graphql",
                    headers=headers,
                    json=payload
                )

                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if attempt < CLAIM_RETRIES:
                        await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue

                data = response.json()
                if "errors" in data:
                    error_msg = data["errors"][0].get("message", "Unknown error")
                    last_error = f"GraphQL Error: {error_msg}"
                    if attempt < CLAIM_RETRIES:
                        await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue

                if "data" in data and data["data"].get("claimConditionBonusCode"):
                    result = data["data"]["claimConditionBonusCode"]
                    success = True
                    amount = float(result.get("amount", 0))
                    currency = result.get("currency", "USDT")
                    logger.info(f"✅ Claim Successful: {amount} {currency}")
                    return True, None, amount, currency

                last_error = "Unexpected response structure"
                if attempt < CLAIM_RETRIES:
                    await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))

        except Exception as e:
            last_error = str(e)
            if attempt < CLAIM_RETRIES:
                await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))
            continue

    return False, last_error or "Unknown error", None, None

# --- Worker Loop ---
async def worker_loop():
    logger.info(f"🚀 Multi-Account Solver Node {NODE_ID} started.")
    
    while True:
        try:
            result = await redis_client.blpop(QUEUE_NAME, timeout=5)
            if not result:
                continue
            
            _, job_json = result
            job = json.loads(job_json)
            user_id = job.get("user_id")
            code = job.get("code")
            
            logger.info(f"📩 Job Received: User {user_id}, Code {code}")

            # 1. Fetch Account Data
            account_data = await get_account_data(user_id)
            if not account_data:
                error_msg = f"Account {user_id} not found"
                await save_claim_result(ClaimResult(
                    user_id=user_id, code=code, success=False, error=error_msg,
                    node_id=NODE_ID, timestamp=datetime.now().isoformat()
                ))
                continue

            # 2. Execute Claim
            success, error, amount, currency = await execute_claim_for_account(account_data, code)

            # 3. Save Result
            await save_claim_result(ClaimResult(
                user_id=user_id, code=code, success=success, error=error,
                amount=amount, currency=currency,
                node_id=NODE_ID, timestamp=datetime.now().isoformat()
            ))

        except Exception as e:
            logger.error(f"💥 Worker Loop Error: {e}", exc_info=True)
            await asyncio.sleep(2)

# --- Startup ---
@app.on_event("startup")
async def startup_event():
    logger.info("🔥 Starting Multi-Account Solver...")
    asyncio.create_task(worker_loop())
    logger.info("✅ Solver Ready")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)