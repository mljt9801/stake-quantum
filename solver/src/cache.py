import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Callable, Awaitable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class TokenEntry:
    token: str
    created_at: datetime
    expires_at: datetime
    is_used: bool = False

class TokenCache:
    def __init__(self, solver_func: Callable[[], Awaitable[str]], min_tokens: int = 2, max_tokens: int = 3):
        self.solver_func = solver_func
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.tokens: List[TokenEntry] = []
        self.lock = asyncio.Lock()
        self.is_refilling = False
        self.is_running = True

    async def _initial_warmup(self):
        """Generates the initial batch of tokens on startup"""
        logger.info("🔥 Warming up token cache...")
        for _ in range(self.min_tokens):
            await self._generate_single_token()
        logger.info(f"✅ Warm-up complete. Cache size: {len(self.tokens)}")

    async def get_token(self) -> str:
        """Get a token. Triggers refill if count < min_tokens."""
        async with self.lock:
            now = datetime.now()
            # Clean expired/used tokens
            self.tokens = [t for t in self.tokens if not t.is_used and t.expires_at > now]
            
            if not self.tokens:
                logger.warning("⚠️ Cache empty! Blocking for generation...")
                token_obj = await self._generate_single_token()
                return token_obj.token
            
            # Pop the first valid token
            entry = self.tokens.pop(0)
            entry.is_used = True
            
            # Trigger background refill if below threshold
            if len(self.tokens) < self.min_tokens and not self.is_refilling:
                self.is_refilling = True
                asyncio.create_task(self._background_refill())
            
            return entry.token

    async def _background_refill(self):
        """Non-blocking refill"""
        try:
            await self._generate_single_token()
        except Exception as e:
            logger.error(f"❌ Refill failed: {e}")
        finally:
            self.is_refilling = False

    async def _generate_single_token(self) -> TokenEntry:
        """Calls the solver and adds to cache"""
        raw_token = await self.solver_func()
        if not raw_token:
            raise ValueError("Solver returned empty token")
        
        # Conservative expiry (90s instead of 120s)
        now = datetime.now()
        entry = TokenEntry(
            token=raw_token,
            created_at=now,
            expires_at=now + timedelta(seconds=90)
        )
        
        async with self.lock:
            if len(self.tokens) < self.max_tokens:
                self.tokens.append(entry)
            else:
                logger.debug("Cache full, discarding new token.")
        
        return entry