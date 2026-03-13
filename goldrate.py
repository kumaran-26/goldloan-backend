import re
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright

URL = "https://www.goodreturns.in/gold-rates/madurai.html"
TIMEOUT = 45000  # Reduced timeout


async def scrape_gold_rates(url: str) -> dict:
    """Scrape gold rates with robust error handling"""
    
    async with async_playwright() as p:
        # Launch browser with anti-detection settings
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        
        page = await context.new_page()
        
        # Block unnecessary resources for faster loading
        await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,eot}", lambda route: route.abort())
        await page.route("**/ads/*", lambda route: route.abort())
        await page.route("**/analytics/*", lambda route: route.abort())
        await page.route("**/tracking/*", lambda route: route.abort())
        await page.route("**/doubleclick.net/*", lambda route: route.abort())
        await page.route("**/googlesyndication.com/*", lambda route: route.abort())
        
        try:
            print(f"🔍 Loading: {url}")
            
            # Use 'domcontentloaded' instead of 'networkidle' - much faster!
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
            
            # Wait for the gold rate content specifically
            await page.wait_for_selector("text=24K Gold", timeout=20000)
            await page.wait_for_timeout(1000)  # Small delay for any lazy-loaded content
            
            # Extract date from heading
            date_text = ""
            date_el = page.locator("h1 + p, h2:has-text('March'), h2:has-text('February')").first
            if await date_el.count() > 0:
                date_text = (await date_el.text_content()).strip()
            current_date = date_text if date_text else datetime.now().strftime("%d %B %Y")
            
            # Extract gold rates using the ACTUAL page structure
            gold_rates = {}
            
            for carat in ["24K", "22K", "18K"]:
                # Find the carat label: "24K Gold /g"
                label = page.locator(f"text=/{carat}\\s*Gold\\s*\\/\\s*g/i").first
                
                if await label.count() > 0:
                    # Get the parent container that holds both label and price
                    container = label.locator("xpath=ancestor::div[contains(@class, 'rate') or contains(@class, 'gold')][1] | ancestor::div[.//text()[contains(., '₹')]][1]").first
                    
                    if await container.count() > 0:
                        container_text = await container.text_content()
                    else:
                        # Fallback: get nearby text after the label
                        container_text = await label.locator("xpath=following-sibling::text()[1] | following::text()[contains(., '₹')][1]").first.text_content()
                    
                    # Extract price using regex
                    price = extract_price(container_text)
                    
                    if price:
                        gold_rates[carat] = {
                            "price_per_gram": price,
                            "currency": "INR",
                            "unit": "gram",
                            "purity": get_purity(carat)
                        }
            
            # Fallback: Parse from full page text if selectors fail
            if not gold_rates:
                page_text = await page.content()
                gold_rates = extract_from_text(page_text)
            
            await browser.close()
            
            return {
                "success": True,
                "location": "Madurai",
                "date": current_date,
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
                "source_url": url,
                "gold_rates": gold_rates
            }
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            await browser.close()
            return {"success": False, "error": str(e), "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")}


def extract_price(text: str) -> int | None:
    """Extract numeric price from text like '₹16,495' or '₹16,495 - ₹87'"""
    if not text:
        return None
    # Find first price after ₹ symbol (the today's price, not the change)
    matches = re.findall(r'₹\s*([\d,]+\.?\d*)', text)
    if matches:
        # First match is today's price, second is change (if present)
        return int(matches[0].replace(",", ""))
    return None


def extract_from_text(page_text: str) -> dict:
    """Fallback: Extract rates from raw HTML text"""
    gold_rates = {}
    
    for carat in ["24K", "22K", "18K"]:
        # Pattern: "24K Gold /g" followed by price like "₹16,495"
        pattern = rf'{carat}\s*Gold\s*/\s*g\s*[^\n]*\n\s*₹\s*([\d,]+)'
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            price = int(match.group(1).replace(",", ""))
            gold_rates[carat] = {
                "price_per_gram": price,
                "currency": "INR",
                "unit": "gram",
                "purity": get_purity(carat)
            }
    
    return gold_rates


def get_purity(carat: str) -> str:
    """Return gold purity percentage"""
    return {"24K": "99.9%", "22K": "91.6%", "18K": "75.0%"}.get(carat, "Unknown")


def display_results(data: dict) -> None:
    """Display results in formatted table"""
    print("\n" + "═" * 75)
    print(f"🏆 GOLD RATES IN {data.get('location', 'UNKNOWN').upper()}")
    print(f"📅 Date: {data.get('date', 'N/A')}")
    print(f"🔄 Scraped at: {data.get('scraped_at', 'N/A')}")
    print("═" * 75)
    
    if not data.get('success'):
        print(f"❌ Error: {data.get('error', 'Unknown error')}")
        return
    
    rates = data.get('gold_rates', {})
    if not rates:
        print("⚠️ No gold rates found. Try running again or check website structure.")
        return
    
    print(f"\n{'Carat':<10} {'Purity':<10} {'Price/Gram':<15} {'Currency':<10}")
    print("-" * 75)
    
    for carat in ["24K", "22K", "18K"]:
        if carat in rates:
            rate = rates[carat]
            print(f"{carat:<10} {rate['purity']:<10} ₹{rate['price_per_gram']:,}{' ':<8} {rate['currency']:<10}")
        else:
            print(f"{carat:<10} {'N/A':<10} {'Not available':<15} {'-':<10}")
    
    print("═" * 75 + "\n")


def save_to_json(data: dict, filename: str = None) -> str:
    """Save results to JSON file"""
    if filename is None:
        filename = f"gold_rates_madurai_{datetime.now().strftime('%Y%m%d')}.json"
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Data saved to: {filename}")
    return filename


# ============= MAIN =============
async def main():
    print("🚀 Gold Rate Scraper - GoodReturns.in (Madurai)")
    print(f"📍 URL: {URL}\n")
    
    result = await scrape_gold_rates(URL)
    display_results(result)
    
    if result.get('success') and result.get('gold_rates'):
        save_to_json(result)
    
    return result


if __name__ == "__main__":
    asyncio.run(main())