# main.py
import re
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# Import your spider
from scraper.spiders.gold_spider import GoldRateSpider
from scraper.items import GoldRateItem

app = FastAPI(title="Gold Rates API - Scrapy")

# ============= GLOBAL CACHE =============
gold_cache: Dict[str, Any] = {}
cache_timestamp: Optional[float] = None
CACHE_TTL = 600  # 10 minutes


# ============= SCRAPY RUNNER (SYNC, THREAD-SAFE) =============
def _run_scrapy_once() -> Dict[str, Any]:
    """Run Scrapy spider synchronously (BLOCKING)"""
    results = {}
    meta_data = {}
    errors = []

    def collect_item(item, response, spider):
        if isinstance(item, GoldRateItem):
            results[item["carat"]] = {
                "price_per_gram": item["price_per_gram"],
                "currency": item["currency"],
                "unit": item["unit"],
                "purity": item["purity"]
            }
        elif isinstance(item, dict) and "_meta" in item:
            meta_data.update(item["_meta"])

    try:
        settings = get_project_settings()
        settings.set("LOG_LEVEL", "ERROR")
        settings.set("CONCURRENT_REQUESTS", 1)
        
        process = CrawlerProcess(settings)
        process.crawl(GoldRateSpider, callback=collect_item)
        process.start(stop_after_crawl=True, install_signal_handlers=False)
        
    except Exception as e:
        errors.append(str(e))
        print(f"❌ Scrapy error: {e}")
    
    if errors and not results:
        return {"success": False, "error": "; ".join(errors)}
    
    if not results:
        return {"success": False, "error": "No gold rates found - check selectors"}
    
    return {
        "success": True,
        "location": "Madurai",
        "date": meta_data.get("date", datetime.now().strftime("%d %B %Y")),
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "source_url": "https://www.goodreturns.in/gold-rates/madurai.html",
        "gold_rates": results
    }


def scrape_gold_rates_sync() -> Dict[str, Any]:
    """Thread-safe wrapper with timeout protection"""
    result_container = {"done": False, "result": None}
    
    def target():
        result_container["result"] = _run_scrapy_once()
        result_container["done"] = True
    
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=45)
    
    if not result_container["done"]:
        return {"success": False, "error": "Scraping timed out (45s)"}
    
    return result_container["result"] or {"success": False, "error": "Unknown error"}


# ============= BACKGROUND SCHEDULER (THREAD-BASED) =============
def _background_scheduler():
    """Runs in dedicated thread: scrapes every 10 minutes"""
    global gold_cache, cache_timestamp  # ✅ Declare FIRST
    
    print("🔄 Background scheduler started (10-min interval)")
    
    while True:
        try:
            print(f"⏰ Scheduled scrape at {datetime.now().strftime('%H:%M:%S')}")
            result = scrape_gold_rates_sync()
            
            if result.get("success") and result.get("gold_rates"):
                gold_cache = result  # ✅ Now safe to modify
                cache_timestamp = time.time()
                print(f"✅ Cache updated: {list(result['gold_rates'].keys())}")
            else:
                print(f"⚠️ Scheduled scrape failed: {result.get('error')}")
                
        except Exception as e:
            print(f"❌ Scheduler error: {e}")
        
        time.sleep(CACHE_TTL)


# ============= FASTAPI ENDPOINTS =============
@app.get("/gold/today")
def get_gold_today(refresh: bool = False):
    """Main endpoint: Returns cached gold rates"""
    global gold_cache, cache_timestamp  # ✅ Declare FIRST, before any use
    
    current_time = time.time()
    
    # Return cached if valid and not forcing refresh
    if not refresh and gold_cache and cache_timestamp and (current_time - cache_timestamp < CACHE_TTL):
        return {
            "success": True,
            "cached": True,
            "data": gold_cache,
            "last_updated": datetime.fromtimestamp(cache_timestamp).strftime("%Y-%m-%d %H:%M:%S IST"),
            "next_update_in_seconds": max(0, int(CACHE_TTL - (current_time - cache_timestamp)))
        }
    
    # Fresh scrape
    result = scrape_gold_rates_sync()
    
    if result.get("success") and result.get("gold_rates"):
        gold_cache = result
        cache_timestamp = time.time()
        return {
            "success": True,
            "cached": False,
            "data": result,
            "last_updated": datetime.fromtimestamp(cache_timestamp).strftime("%Y-%m-%d %H:%M:%S IST")
        }
    
    # Fallback to stale cache
    if gold_cache and not refresh:
        return {
            "success": False,
            "cached": True,
            "warning": "Live scrape failed, returning cached data",
            "data": gold_cache
        }
    
    raise HTTPException(
        status_code=502,
        detail={
            "success": False, 
            "error": result.get("error", "Failed to fetch"), 
            "message": "Unable to retrieve gold prices"
        }
    )


@app.get("/gold/refresh")
def refresh_gold():
    """Force immediate fresh scrape"""
    global gold_cache, cache_timestamp  # ✅ Declare FIRST
    
    print("🔄 Manual refresh requested")
    result = scrape_gold_rates_sync()
    
    if result.get("success"):
        gold_cache = result
        cache_timestamp = time.time()
        return {"success": True, "message": "Refreshed", "data": result}
    
    return {"success": False, "error": result.get("error")}


@app.get("/health")
def health_check():
    """Health & status endpoint"""
    # ✅ No global needed - only READ, never WRITE
    return {
        "status": "ok",
        "cache_has_data": bool(gold_cache),
        "last_updated": datetime.fromtimestamp(cache_timestamp).strftime("%Y-%m-%d %H:%M:%S") if cache_timestamp else None,
        "cache_ttl_seconds": CACHE_TTL,
        "scheduler_active": True
    }


@app.get("/debug/scrape")
def debug_scrape():
    """Debug: run scrape and return raw result"""
    result = scrape_gold_rates_sync()
    return result


# ============= STARTUP/SHUTDOWN =============
@app.on_event("startup")
def startup():
    """Startup: initial scrape + start background scheduler"""
    global gold_cache, cache_timestamp  # ✅ Declare FIRST
    
    print("🚀 Starting Gold Rates API (Scrapy + Threads)")
    
    # Initial scrape
    print("🔍 Running initial scrape...")
    result = scrape_gold_rates_sync()
    
    if result.get("success"):
        gold_cache = result
        cache_timestamp = time.time()
        print(f"✅ Initial cache populated: {list(result['gold_rates'].keys())}")
    else:
        print(f"⚠️ Initial scrape failed: {result.get('error')}")
    
    # Start background scheduler thread
    scheduler_thread = threading.Thread(target=_background_scheduler, daemon=True)
    scheduler_thread.start()
    print("✅ Background scheduler thread started")


@app.on_event("shutdown")
def shutdown():
    """Cleanup on shutdown"""
    print("🛑 Shutting down Gold Rates API")