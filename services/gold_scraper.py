# services/gold_scraper.py
import re
import logging
import traceback
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from config import GOLD_SCRAPER_URL, SCRAPER_TIMEOUT, HEADLESS, SUPPORTED_CARATS, DEFAULT_LOCATION, GOLD_RATE_CACHE_TTL
from .cache import cached

logger = logging.getLogger(__name__)

class GoldRateScrapingError(Exception):
    """Custom exception for scraper errors"""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error

async def _extract_price_for_carat(page, carat: str) -> Optional[int]:
    """Extract price for a specific carat type from the page."""
    try:
        logger.info(f"🔍 Looking for {carat} Gold...")
        
        # Try multiple selector strategies
        selectors = [
            f"text={carat} Gold",
            f"text={carat}",
            f"xpath=//*[contains(text(), '{carat}')]",
        ]
        
        carat_locator = None
        for selector in selectors:
            try:
                carat_locator = page.locator(selector).first
                if await carat_locator.count() > 0:
                    logger.info(f"✅ Found {carat} with selector: {selector}")
                    break
            except:
                continue
        
        if not carat_locator or await carat_locator.count() == 0:
            logger.warning(f"❌ Could not find {carat} Gold label with any selector")
            # Debug: Print page content
            content = await page.content()
            logger.debug(f"Page content snippet: {content[:500]}...")
            return None
        
        # Try to find price near the carat label
        price = None
        
        # Strategy 1: Look for ₹ in parent container
        try:
            parent = carat_locator.locator("xpath=..")
            price_text = await parent.text_content()
            match = re.search(r'₹\s*([\d,]+)', price_text or "")
            if match:
                price = int(match.group(1).replace(",", ""))
                logger.info(f"✅ Found {carat} price in parent: ₹{price}")
        except Exception as e:
            logger.debug(f"Parent search failed: {e}")
        
        # Strategy 2: Look for ₹ in following siblings
        if not price:
            try:
                siblings = carat_locator.locator("xpath=following-sibling::*")
                for i in range(await siblings.count()):
                    sibling_text = await siblings.nth(i).text_content()
                    match = re.search(r'₹\s*([\d,]+)', sibling_text or "")
                    if match:
                        price = int(match.group(1).replace(",", ""))
                        logger.info(f"✅ Found {carat} price in sibling: ₹{price}")
                        break
            except Exception as e:
                logger.debug(f"Sibling search failed: {e}")
        
        # Strategy 3: Search entire page for carat + price pattern
        if not price:
            try:
                all_text = await page.locator("body").text_content()
                # Look for pattern like "24K Gold ... ₹16,331"
                pattern = rf'{carat}.*?₹\s*([\d,]+)'
                match = re.search(pattern, all_text or "", re.DOTALL)
                if match:
                    price = int(match.group(1).replace(",", ""))
                    logger.info(f"✅ Found {carat} price via regex: ₹{price}")
            except Exception as e:
                logger.debug(f"Regex search failed: {e}")
        
        if not price:
            logger.warning(f"❌ Could not extract price for {carat}")
            # Debug: Save screenshot
            await page.screenshot(path=f"debug_{carat}_no_price.png")
            return None
        
        return price
        
    except Exception as e:
        logger.error(f"❌ Error extracting {carat} price: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

@cached(ttl=GOLD_RATE_CACHE_TTL, key_prefix="gold_rates")
async def scrape_gold_rates(location: str = DEFAULT_LOCATION) -> dict:
    """Scrape gold rates from goodreturns.in"""
    browser = None
    
    try:
        logger.info(f"🚀 Starting scrape for {location}...")
        logger.info(f"📍 URL: {GOLD_SCRAPER_URL}")
        
        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Enable request/response logging
            page.on("request", lambda req: logger.debug(f"📤 Request: {req.url}"))
            page.on("response", lambda res: logger.debug(f"📥 Response: {res.status} - {res.url}"))
            
            # Navigate
            logger.info("🌐 Navigating to page...")
            await page.goto(
                GOLD_SCRAPER_URL, 
                wait_until="domcontentloaded",
                timeout=SCRAPER_TIMEOUT * 1000
            )
            
            # Take screenshot for debugging
            await page.screenshot(path="debug_page_loaded.png")
            logger.info("📸 Screenshot saved: debug_page_loaded.png")
            
            # Wait for content
            try:
                await page.wait_for_selector("text=Gold", timeout=10000)
                logger.info("✅ Gold content found on page")
            except Exception as e:
                logger.error(f"❌ Wait for selector failed: {e}")
                await page.screenshot(path="debug_no_gold_content.png")
                raise GoldRateScrapingError(
                    "Page loaded but gold content not found",
                    original_error=e
                )
            
            # Scrape each carat
            gold_rates = {}
            errors = []
            
            for carat in SUPPORTED_CARATS:
                logger.info(f"🔍 Extracting {carat}...")
                price = await _extract_price_for_carat(page, carat)
                
                if price:
                    gold_rates[carat] = {
                        "price_per_gram": price,
                        "currency": "INR"
                    }
                else:
                    errors.append(f"Failed to extract {carat} price")
                    gold_rates[carat] = {
                        "price_per_gram": None,
                        "currency": "INR",
                        "error": "Price not found"
                    }
            
            if errors:
                logger.warning(f"⚠️ Partial scrape. Errors: {errors}")
            
            result = {
                "location": location,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "timestamp": datetime.now().isoformat(),
                "gold_rates": gold_rates,
                "source": "goodreturns.in",
                "disclaimer": "Rates are indicative. Contact local jeweller for exact prices."
            }
            
            logger.info(f"✅ Successfully scraped gold rates for {location}")
            return result
            
    except PlaywrightTimeout as e:
        logger.error(f"⏱️ Timeout: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise GoldRateScrapingError(
            f"Website took too long to respond (timeout: {SCRAPER_TIMEOUT}s)",
            original_error=e
        )
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"❌ Unexpected error: {error_msg}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise GoldRateScrapingError(
            f"Scraping failed: {error_msg}",
            original_error=e
        )
        
    finally:
        if browser:
            try:
                await browser.close()
                logger.info("🔒 Browser closed")
            except Exception as e:
                logger.warning(f"⚠️ Error closing browser: {e}")