# config.py
from datetime import timedelta

# Scraper Settings
GOLD_SCRAPER_URL = "https://www.goodreturns.in/gold-rates/madurai.html"
DEFAULT_LOCATION = "Madurai"

# Scrapy Settings
SCRAPY_LOG_LEVEL = "WARNING"
SCRAPY_DOWNLOAD_DELAY = 1
SCRAPY_CONCURRENT_REQUESTS = 1
SCRAPY_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Cache Settings (seconds)
GOLD_RATE_CACHE_TTL = timedelta(hours=2).total_seconds()

# Supported carats & metadata
SUPPORTED_CARATS = ["24K", "22K", "18K"]
GOLD_PURITY = {"24K": "99.9%", "22K": "91.6%", "18K": "75.0%"}