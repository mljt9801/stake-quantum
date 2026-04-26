import asyncio
import json
import logging
import os
import uuid
import time
from datetime import datetime
from typing import Optional, Tuple
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

# Import local modules
from .cache import TokenCache
from .solver import CamofoxSolver
from .runtime_manager import RuntimeAccountManager
from .config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB, REDIS_SSL,
    NODE_ID, QUEUE_NAME, RESULT_CHANNEL,
    STAKE_BASE_URL, CLAIM_CURRENCY, CLAIM_RETRIES, CLAIM_BACKOFF_BASE,
    ACCOUNT_EVENTS_CHANNEL, TOKEN_POOL_TARGET, TOKEN_TTL_SECONDS,
    TOKEN_REFRESH_MARGIN_SECONDS, TOKEN_MAINTAIN_INTERVAL_SECONDS,
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
solver_instance = CamofoxSolver()
token_cache = TokenCache(solver_func=solver_instance.solve_turnstile, min_tokens=2, max_tokens=3)
runtime_account_manager = None

# --- Async Redis Client ---
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD if REDIS_PASSWORD else None,
    db=REDIS_DB,
    ssl=REDIS_SSL,
    decode_responses=True,
    socket_timeout=15,
    socket_connect_timeout=5
)

# --- Models ---
class ClaimJob(BaseModel):
    user_id: str
    code: str
    proxy_url: Optional[str] = None

class ClaimResult(BaseModel):
    user_id: str
    code: str
    success: bool
    error: Optional[str] = None
    node_id: str
    timestamp: str


async def solve_runtime_account(account) -> str:
    return await solver_instance.solve_turnstile(
        cookies_json=account.cookies_json,
        user_agent=account.user_agent,
        proxy_url=account.proxy_url,
    )

# --- Health Check ---
@app.get("/health")
async def health():
    try:
        await redis_client.ping()
        cache_size = len(token_cache.tokens)
        runtime_accounts = len(runtime_account_manager.accounts) if runtime_account_manager else 0
        return {
            "status": "healthy",
            "node_id": NODE_ID,
            "cache_size": cache_size,
            "redis_connected": True,
            "runtime_accounts": runtime_accounts,
        }
    except Exception as e:
        return {
            "status": "degraded",
            "node_id": NODE_ID,
            "cache_size": len(token_cache.tokens),
            "runtime_accounts": len(runtime_account_manager.accounts) if runtime_account_manager else 0,
            "redis_connected": False,
            "error": str(e)
        }

# --- Manual Trigger (Debug) ---
@app.post("/force-solve")
async def force_solve():
    try:
        token = await token_cache.get_token()
        return {
            "status": "success",
            "token_preview": f"{token[:10]}...",
            "cache_size": len(token_cache.tokens)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Claim Execution Logic with Retry ---
async def execute_claim(code: str, token: str, proxy_url: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Executes the claim request with retry logic and structured error handling.
    Returns (success, error_message).
    """
    headers = {
        "Content-Type": "application/json",
        "Origin": STAKE_BASE_URL,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-operation-name": "ClaimConditionBonusCode"
    }
    
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
    
    for attempt in range(1, CLAIM_RETRIES + 1):
        try:
            async with httpx.AsyncClient(proxies=proxies, timeout=30.0) as client:
                response = await client.post(
                    f"{STAKE_BASE_URL}/_api/graphql",
                    headers=headers,
                    json=payload
                )
                
                # Handle HTTP Errors
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.warning(f"Attempt {attempt}/{CLAIM_RETRIES} failed: {last_error}")
                    if attempt < CLAIM_RETRIES:
                        await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue
                
                # Parse JSON Response
                try:
                    data = response.json()
                except json.JSONDecodeError:
                    last_error = f"Invalid JSON response: {response.text[:200]}"
                    logger.error(last_error)
                    return False, last_error
                
                # Check for GraphQL Errors
                if "errors" in data:
                    error_msg = data["errors"][0].get("message", "Unknown GraphQL error")
                    error_type = data["errors"][0].get("extensions", {}).get("errorType", "unknown")
                    
                    # Specific handling for known errors
                    if error_type in ["notFound", "bonusCodeInactive", "codeAlreadyClaimed"]:
                        logger.info(f"Claim failed (expected): {error_msg}")
                        return False, error_msg
                    
                    last_error = f"GraphQL Error: {error_msg}"
                    logger.warning(f"Attempt {attempt}/{CLAIM_RETRIES} failed: {last_error}")
                    if attempt < CLAIM_RETRIES:
                        await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue
                
                # Check for Success
                if "data" in data and data["data"].get("claimConditionBonusCode"):
                    result = data["data"]["claimConditionBonusCode"]
                    logger.info(f"Claim successful: {result['amount']} {result['currency']}")
                    return True, None
                
                # Unexpected response structure
                last_error = f"Unexpected response structure: {data}"
                logger.error(last_error)
                return False, last_error
                
        except httpx.RequestError as e:
            last_error = f"Request error: {str(e)}"
            logger.warning(f"Attempt {attempt}/{CLAIM_RETRIES} failed: {last_error}")
            if attempt < CLAIM_RETRIES:
                await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))
            continue
        except Exception as e:
            last_error = f"Unexpected error: {str(e)}"
            logger.error(f"Attempt {attempt}/{CLAIM_RETRIES} failed: {last_error}")
            if attempt < CLAIM_RETRIES:
                await asyncio.sleep(CLAIM_BACKOFF_BASE * (2 ** (attempt - 1)))
            continue
    
    logger.error(f"All {CLAIM_RETRIES} attempts failed. Last error: {last_error}")
    return False, last_error or "Unknown error"

# --- The Worker Loop (Background Task) ---
async def worker_loop():
    logger.info(f"🚀 Solver Node {NODE_ID} started. Connecting to Redis...")
    
    while True:
        try:
            # 1. Blocking Pop from Queue (Async)
            result = await redis_client.blpop(QUEUE_NAME, timeout=5)
            
            if not result:
                continue
            
            _, job_json = result
            job = json.loads(job_json)
            
            user_id = job.get("user_id")
            code = job.get("code")
            proxy = job.get("proxy_url")
            
            logger.info(f"📩 Job Received: User {user_id} | Code {code} | Proxy: {'Yes' if proxy else 'No'}")
            
            # 2. Get Token from Local Cache
            try:
                token = await token_cache.get_token()
                logger.info(f"✅ Token Retrieved from Cache (Size: {len(token_cache.tokens)})")
            except Exception as e:
                logger.error(f"❌ Failed to get token from cache: {e}")
                result_payload = ClaimResult(
                    user_id=user_id,
                    code=code,
                    success=False,
                    error=f"Token generation failed: {e}",
                    node_id=NODE_ID,
                    timestamp=datetime.now().isoformat()
                )
                await redis_client.publish(RESULT_CHANNEL, result_payload.model_dump_json())
                continue
            
            # 3. Execute Claim with Retry
            success, error_msg = await execute_claim(code, token, proxy)
            
            # 4. Publish Result
            result_payload = ClaimResult(
                user_id=user_id,
                code=code,
                success=success,
                error=error_msg,
                node_id=NODE_ID,
                timestamp=datetime.now().isoformat()
            )
            
            await redis_client.publish(RESULT_CHANNEL, result_payload.model_dump_json())
            logger.info(f"📤 Result Published: {success}")
            
        except Exception as e:
            logger.error(f"💥 Worker Loop Error: {e}", exc_info=True)
            await asyncio.sleep(2)

# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    global runtime_account_manager
    logger.info("🔥 Initializing Token Cache (Warming up 2 tokens)...")
    runtime_account_manager = RuntimeAccountManager(
        redis_client=redis_client,
        solver_func=solve_runtime_account,
        target_tokens=TOKEN_POOL_TARGET,
        token_ttl_seconds=TOKEN_TTL_SECONDS,
        refresh_margin_seconds=TOKEN_REFRESH_MARGIN_SECONDS,
        maintain_interval_seconds=TOKEN_MAINTAIN_INTERVAL_SECONDS,
    )
    await runtime_account_manager.load_enabled_accounts()

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(ACCOUNT_EVENTS_CHANNEL)
    asyncio.create_task(runtime_account_manager.run_event_listener(pubsub))
    asyncio.create_task(token_cache._initial_warmup())
    asyncio.create_task(worker_loop())
    logger.info("✅ Solver Node Ready for Jobs")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
