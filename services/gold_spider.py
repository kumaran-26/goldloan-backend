# services/scraper_service.py
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from scrapy.utils.log import configure_logging
from twisted.internet import asyncioreactor

# ⚠️ Install asyncioreactor BEFORE importing scrapy modules
asyncioreactor.install()

from spiders.gold_spider import GoldRateSpider
from config import (
    GOLD_SCRAPER_URL,
    DEFAULT_LOCATION,
    GOLD_RATE_CACHE_TTL,
    SCRAPY_LOG_LEVEL,
    SCRAPY_DOWNLOAD_DELAY,
    SCRAPY_CONCURRENT_REQUESTS,
    SCRAPY_USER_AGENT,
)

logger = logging.getLogger(__name__)

# Simple in-memory cache
_cache: Dict[str, tuple[dict, float]] = {}


def _get_cache_key(location: str) -> str:
    return f"gold_rates:{location}"


def _cache_get(key: str) -> Optional[dict]:
    """Get from cache if not expired"""
    if key not in _cache:
        return None
    value, expiry = _cache[key]
    if datetime.now().timestamp() > expiry:
        _cache.pop(key, None)
        return None
    logger.info(f"📦 Cache hit for {key}")
    return value


def _cache_set(key: str, value: dict, ttl: float):
    """Store in cache with expiry"""
    expiry = datetime.now().timestamp() + ttl
    _cache[key] = (value, expiry)
    logger.info(f"💾 Cached {key} for {ttl}s")


async def run_spider(location: str = DEFAULT_LOCATION) -> dict:
    """
    Run Scrapy spider and return results.
    Uses CrawlerRunner with asyncioreactor for async compatibility.
    """
    
    # Configure Scrapy settings
    settings = get_project_settings()
    settings.set("LOG_LEVEL", SCRAPY_LOG_LEVEL)
    settings.set("DOWNLOAD_DELAY", SCRAPY_DOWNLOAD_DELAY)
    settings.set("CONCURRENT_REQUESTS", SCRAPY_CONCURRENT_REQUESTS)
    settings.set("USER_AGENT", SCRAPY_USER_AGENT)
    settings.set("ROBOTSTXT_OBEY", False)
    
    # Create runner
    runner = CrawlerRunner(settings)
    
    # Container for spider result
    result_container = {"data": None, "error": None}
    
    def handle_result(item):
        """Callback to capture scraped item"""
        result_container["data"] = item
    
    def handle_error(failure):
        """Callback to capture errors"""
        logger.error(f"❌ Spider error: {failure.getErrorMessage()}")
        result_container["error"] = str(failure.getErrorMessage())
    
    try:
        logger.info(f"🕷️ Starting Scrapy spider for {location}...")
        
        # Run spider with callbacks
        d = runner.crawl(
            GoldRateSpider,
            location=location,
            result_callback=handle_result,
            error_callback=handle_error
        )
        
        # Wait for spider to complete
        await d
        
        if result_container["error"]:
            raise Exception(result_container["error"])
        
        if not result_container["data"]:
            raise Exception("Spider completed but no data returned")
        
        logger.info(f"✅ Spider completed for {location}")
        return result_container["data"]
        
    except Exception as e:
        logger.error(f"❌ Error running spider: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "location": location,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        }


async def get_gold_rates(location: str = DEFAULT_LOCATION) -> dict:
    """
    Get gold rates with caching support.
    Main entry point for the API.
    """
    cache_key = _get_cache_key(location)
    
    # Try cache first
    cached = _cache_get(cache_key)
    if cached:
        return cached
    
    # Run spider
    result = await run_spider(location)
    
    # Cache successful results
    if result.get("success"):
        _cache_set(cache_key, result, GOLD_RATE_CACHE_TTL)
    
    return result