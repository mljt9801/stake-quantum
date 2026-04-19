import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import List, Callable, Awaitable
from dataclasses import dataclass

# Try to import playwright, install if missing
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Installing Playwright...")
    import subprocess
    subprocess.check_call(["pip", "install", "playwright"])
    subprocess.check_call(["playwright", "install", "firefox"])
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration ---
CAMOFOX_PATH = os.getenv("CAMOFOX_PATH", "/usr/local/bin/camofox-firefox") # Update this path if running locally
MIN_TOKENS = 2
MAX_TOKENS = 3
SOLVER_TIMEOUT = 30

@dataclass
class TokenEntry:
    token: str
    expires_at: datetime
    is_used: bool = False

class TokenCache:
    def __init__(self, solver_func: Callable[[], Awaitable[str]]):
        self.solver_func = solver_func
        self.tokens: List[TokenEntry] = []
        self.lock = asyncio.Lock()
        self.is_refilling = False

    async def _generate_token(self) -> TokenEntry:
        raw_token = await self.solver_func()
        if not raw_token:
            raise ValueError("Solver returned empty token")
        return TokenEntry(
            token=raw_token,
            expires_at=datetime.now() + timedelta(seconds=90),
            is_used=False
        )

    async def get_token(self) -> str:
        async with self.lock:
            # Clean expired
            self.tokens = [t for t in self.tokens if not t.is_used and t.expires_at > datetime.now()]
            
            if not self.tokens:
                logger.warning("⚠️ Cache empty! Generating token (slow path)...")
                entry = await self._generate_token()
                self.tokens.append(entry)
                return entry.token
            
            entry = self.tokens.pop(0)
            entry.is_used = True
            
            # Trigger refill if low
            if len(self.tokens) < MIN_TOKENS and not self.is_refilling:
                self.is_refilling = True
                asyncio.create_task(self._background_refill())
            
            return entry.token

    async def _background_refill(self):
        try:
            entry = await self._generate_token()
            async with self.lock:
                if len(self.tokens) < MAX_TOKENS:
                    self.tokens.append(entry)
        except Exception as e:
            logger.error(f"Refill failed: {e}")
        finally:
            self.is_refilling = False

class CamofoxSolver:
    async def solve_turnstile(self) -> str:
        logger.info("🌐 Launching Camofox Firefox to solve Turnstile...")
        async with async_playwright() as p:
            # Fallback to standard firefox if camofox path invalid
            try:
                browser = await p.firefox.launch(
                    executable_path=CAMOFOX_PATH,
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
            except Exception:
                logger.warning("⚠️ Camofox not found, using standard Firefox (lower success rate)")
                browser = await p.firefox.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()
            
            try:
                await page.goto("https://stake.com/zh/settings/offers?type=drop&modal=redeemBonus", wait_until="networkidle", timeout=SOLVER_TIMEOUT * 1000)
                await page.wait_for_selector("iframe[src*='turnstile']", timeout=15000)
                
                token = await page.evaluate("""
                    new Promise((resolve, reject) => {
                        if (typeof turnstile !== 'undefined') {
                            const widgets = turnstile.getWidgetIds();
                            if (widgets.length > 0) {
                                const token = turnstile.getResponse(widgets[0]);
                                if (token) resolve(token);
                                else reject('Token not ready');
                            } else reject('No widget found');
                        } else reject('Turnstile not loaded');
                    })
                """)
                logger.info(f"✅ Token Solved: {token[:20]}...")
                return token
            except PlaywrightTimeout:
                raise Exception("Solve timeout")
            finally:
                await browser.close()

async def main():
    solver = CamofoxSolver()
    cache = TokenCache(solver.solve_turnstile)
    
    logger.info("🔥 Warming up cache...")
    # Pre-generate 2 tokens
    await cache._generate_token()
    await cache._generate_token()
    
    logger.info("✅ Cache ready. Testing claim loop...")
    
    # Simulate 5 claims
    for i in range(5):
        start = datetime.now()
        token = await cache.get_token()
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"🚀 Claim {i+1}: Got token in {elapsed:.3f}s | Cache Size: {len(cache.tokens)}")
        await asyncio.sleep(1) # Simulate claim processing

if __name__ == "__main__":
    asyncio.run(main())