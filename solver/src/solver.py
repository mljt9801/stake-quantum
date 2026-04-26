import asyncio
import json
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import stealth_async
from .config import CAMOFOX_BINARY_PATH, SOLVER_TIMEOUT, USE_STEALTH

logger = logging.getLogger(__name__)

class CamofoxSolver:
    def __init__(self):
        self.browser_path = CAMOFOX_BINARY_PATH if CAMOFOX_BINARY_PATH else None

    async def solve_turnstile(self, *, cookies_json: str = "", user_agent: str = "", proxy_url: str = "") -> str:
        """
        Launches browser, navigates to Stake, solves Turnstile, returns token.
        Includes robust fallback for token extraction.
        """
        async with async_playwright() as p:
            # Launch browser
            launch_kwargs = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if proxy_url:
                launch_kwargs["proxy"] = {"server": proxy_url}

            if self.browser_path:
                try:
                    browser = await p.firefox.launch(
                        executable_path=self.browser_path,
                        **launch_kwargs,
                    )
                    logger.info("🦊 Launched Camofox Firefox")
                except Exception as e:
                    logger.warning(f"⚠️ Camofox failed ({e}), falling back to standard Firefox")
                    browser = await p.firefox.launch(**launch_kwargs)
            else:
                browser = await p.firefox.launch(**launch_kwargs)
            
            context = await browser.new_context(
                user_agent=user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                viewport={"width": 1920, "height": 1080}
            )

            await self._apply_cookies(context, cookies_json)
            
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

    async def _apply_cookies(self, context, cookies_json: str) -> None:
        if not cookies_json:
            return

        try:
            cookies = json.loads(cookies_json)
        except json.JSONDecodeError as exc:
            logger.warning("⚠️ Invalid cookies_json provided to solver: %s", exc)
            return

        normalized = []
        for cookie in cookies:
            if not isinstance(cookie, dict) or "name" not in cookie or "value" not in cookie:
                continue
            normalized.append(
                {
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": cookie.get("domain", ".stake.com"),
                    "path": cookie.get("path", "/"),
                    "httpOnly": cookie.get("httpOnly", False),
                    "secure": cookie.get("secure", True),
                    "sameSite": cookie.get("sameSite", "Lax"),
                }
            )

        if normalized:
            await context.add_cookies(normalized)

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
