import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Reuse the scraper logic you already wrote.
from backend.app.services.goldrate_today import URL, scrape_gold_rates

# Playwright on Windows relies on `asyncio.create_subprocess_exec`.
# Some event loop policies (notably selector-based) raise NotImplementedError for subprocess support.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="Gold Rate API")

app.add_middleware(
    CORSMiddleware,
    # Update this to match where your React app is hosted.
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/gold-rates")
async def get_gold_rates():
    """
    Returns scraped gold rates as JSON.
    """
    try:
        # Run the Playwright scraper in a separate thread so it doesn't
        # inherit uvicorn's event loop (which can be selector-based on Windows).
        def _scrape_sync():
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            return asyncio.run(scrape_gold_rates(URL))

        return await asyncio.to_thread(_scrape_sync)
    except Exception as e:
        # Return the real error instead of a generic 500,
        # so we can debug Playwright/OS issues quickly.
        return {
            "success": False,
            "error": str(e),
            "error_type": e.__class__.__name__,
        }

