import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import stealth_async
from .config import CAMOFOX_BINARY_PATH, SOLVER_TIMEOUT, USE_STEALTH

logger = logging.getLogger(__name__)

class CamofoxSolver:
    def __init__(self):
        self.browser_path = CAMOFOX_BINARY_PATH if CAMOFOX_BINARY_PATH else None

    async def solve_turnstile(self) -> str:
        """
        Launches browser, navigates to Stake, solves Turnstile, returns token.
        Includes robust fallback for token extraction.
        """
        async with async_playwright() as p:
            # Launch browser
            if self.browser_path:
                try:
                    browser = await p.firefox.launch(
                        executable_path=self.browser_path,
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"]
                    )
                    logger.info("🦊 Launched Camofox Firefox")
                except Exception as e:
                    logger.warning(f"⚠️ Camofox failed ({e}), falling back to standard Firefox")
                    browser = await p.firefox.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"]
                    )
            else:
                browser = await p.firefox.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                viewport={"width": 1920, "height": 1080}
            )
            
            # Apply stealth if enabled
            if USE_STEALTH:
                await stealth_async(context)
            
            page = await context.new_page()
            
            try:
                await page.goto(
                    "https://stake.com/zh/settings/offers?type=drop&modal=redeemBonus",
                    wait_until="networkidle",
                    timeout=SOLVER_TIMEOUT * 1000
                )
                
                # Wait for Turnstile iframe
                try:
                    await page.wait_for_selector("iframe[src*='turnstile']", timeout=15000)
                except PlaywrightTimeout:
                    # Fallback: Wait for any iframe
                    await page.wait_for_selector("iframe", timeout=15000)
                
                # Robust Token Extraction
                token = await self._extract_token(page)
                logger.info(f"✅ Token Solved: {token[:20]}...")
                return token
                
            except PlaywrightTimeout:
                logger.error("⏱️ Turnstile timeout")
                raise Exception("Solve timeout")
            except Exception as e:
                logger.error(f"❌ Solve error: {e}")
                raise e
            finally:
                await browser.close()

    async def _extract_token(self, page) -> str:
        """Multiple strategies to extract the token"""
        
        # Strategy 1: Standard Turnstile API
        try:
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
            if token:
                return token
        except Exception as e:
            logger.debug(f"Strategy 1 failed: {e}")
        
        # Strategy 2: Look for hidden input field (fallback)
        try:
            token = await page.evaluate("""
                new Promise((resolve, reject) => {
                    const inputs = document.querySelectorAll('input[type="hidden"]');
                    for (let input of inputs) {
                        if (input.name && input.name.includes('turnstile')) {
                            resolve(input.value);
                            return;
                        }
                    }
                    reject('No hidden input found');
                })
            """)
            if token:
                return token
        except Exception as e:
            logger.debug(f"Strategy 2 failed: {e}")
        
        # Strategy 3: Check page source for token pattern
        content = await page.content()
        import re
        match = re.search(r'"cf-turnstile-response"\s*:\s*"([^"]+)"', content)
        if match:
            return match.group(1)
        
        raise Exception("All token extraction strategies failed")