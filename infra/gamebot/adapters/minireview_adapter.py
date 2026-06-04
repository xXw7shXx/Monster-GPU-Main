import httpx
from bs4 import BeautifulSoup
from loguru import logger
from typing import List
import re
import asyncio
from core.schemas import GameObject

class MiniReviewAdapter:
    def __init__(self):
        self.base_url = "https://minireview.io"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    async def fetch_with_headless(self) -> str:
        """
        Soft-Fail Proxy: Attempt scraping with Playwright if simple HTTP fails.
        """
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                logger.info("[MiniReview] Launching Headless Browser Proxy...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(self.base_url, timeout=30000, wait_until="networkidle")

                # Wait for the actual game items to render
                try:
                    await page.wait_for_selector(".list-games-item", timeout=10000)
                except:
                    logger.warning("[MiniReview] Selector .list-games-item not found, trying fallback...")

                content = await page.content()
                await browser.close()
                return content
        except Exception as e:
            logger.error(f"[MiniReview] Headless proxy failed: {e.__class__.__name__}")
            return None

    async def fetch(self) -> List[GameObject]:
        logger.info("[MiniReview] Fetching mobile games...")

        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True) as client:
            try:
                # 1. Try Simple HTTP
                response = await client.get(self.base_url, timeout=10.0)
                html = response.text if response.status_code == 200 else None

                # 2. Check if we actually got content
                if html:
                    soup = BeautifulSoup(html, "html.parser")
                    if not soup.select(".game-card") and not soup.select(".list-games-item"):
                        logger.warning("[MiniReview] Page skeleton detected. Falling back to Headless Proxy...")
                        html = None

                # 3. Fallback to Headless if blocked/failed/skeleton
                if not html:
                    html = await self.fetch_with_headless()

                if not html:
                    logger.error("[MiniReview] all scraping methods failed")
                    raise RuntimeError("MiniReviewFetchFailed")

                soup = BeautifulSoup(html, "html.parser")
                # Try multiple selectors for the new React/AntDesign/Swiper layout
                cards = (
                    soup.select(".swiper-slide") +
                    soup.select(".card-container") +
                    soup.select(".list-games-item") +
                    soup.select(".ant-card")
                )

                games = []
                for card in cards[:20]:
                    try:
                        # Try finding title in multiple possible locations
                        title_tag = (
                            card.select_one(".title") or
                            card.select_one("h3") or
                            card.select_one("h2") or
                            card.select_one(".col-title") or
                            card.select_one(".ant-card-meta-title")
                        )
                        if not title_tag: continue

                        title = title_tag.get_text(strip=True)
                        if not title or len(title) < 2 or title.upper() in ["HIGHLIGHT", "REVIEW", "TOP GAMES"]: continue

                        # Extract Image
                        image_tag = card.select_one("img")
                        image_url = image_tag.get("src") if image_tag else None
                        if image_url and image_url.startswith("/"):
                            image_url = self.base_url + image_url

                        # Extract Price / Monetization
                        price_tag = card.select_one(".price") or card.select_one(".game-price") or card.select_one(".monetization")
                        price_text = price_tag.get_text(strip=True).lower() if price_tag else ""

                        original_price = 0
                        current_price = 0
                        monetization = "Free"

                        if "premium" in price_text or "$" in price_text:
                            monetization = "Premium"
                            # Attempt to parse price if present, e.g., "$4.99"
                            price_match = re.search(r"\$(\d+\.?\d*)", price_text)
                            if price_match:
                                current_price = int(float(price_match.group(1)) * 100)
                                original_price = current_price
                        elif "free" in price_text:
                            monetization = "Free"

                        # Extract Link (for ID)
                        link_tag = card.select_one("a[href*='/review/']") or card.select_one("a")
                        clean_id = "".join(filter(str.isalnum, title.lower()))
                        if link_tag and "/review/" in link_tag.get("href", ""):
                            clean_id = link_tag.get("href").strip("/").split("/")[-1]

                        games.append(GameObject(
                            external_id=f"MINI-{clean_id}",
                            title=title,
                            platforms="Android, iOS",
                            original_price=original_price,
                            current_price=current_price,
                            platform_type="Mobile",
                            monetization_tags=monetization,
                            source_name="minireview",
                            image_url=image_url,
                            game_type="special"
                        ))
                    except: continue

                if not games:
                    logger.warning("[MiniReview] Scraped 0 games. site structure might have changed again.")
                else:
                    logger.success(f"[MiniReview] Successfully scraped {len(games)} games.")

                return games
            except Exception as e:
                logger.error(f"[MiniReview] fetch failed: {e.__class__.__name__}")
                raise
