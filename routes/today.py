# routers/gold.py
from fastapi import APIRouter, HTTPException, status, Query
from typing import Optional

from services.scraper_service import get_gold_rates
from config import SUPPORTED_CARATS, DEFAULT_LOCATION

router = APIRouter(prefix="/gold-api", tags=["gold"])


@router.get(
    "/gold-rate/today",
    summary="Get today's gold rates for all carats",
    description="Fetch current gold rates for 24K, 22K, and 18K per gram in INR"
)
async def get_gold_rate_today(
    location: Optional[str] = Query(
        default=DEFAULT_LOCATION,
        description="City name for gold rates",
        example="Madurai"
    )
):
    """Get gold rates for all supported carats."""
    try:
        data = await get_gold_rates(location)
        
        if not data.get("success"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=data.get("error", "Failed to fetch gold rates")
            )
        
        return {
            "location": data["location"],
            "date": data["date"],
            "scraped_at": data["scraped_at"],
            "source": data["source_url"],
            "gold_rates": {
                carat: {
                    "price_per_gram": rate["price_per_gram"],
                    "currency": rate["currency"],
                    "unit": rate["unit"],
                    "purity": rate["purity"]
                }
                for carat, rate in data["gold_rates"].items()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching gold rates"
        )


@router.get(
    "/gold-rate/{carat}",
    summary="Get rate for specific carat",
    description="Fetch gold rate for a specific carat type (24K, 22K, or 18K)"
)
async def get_gold_rate_by_carat(
    carat: str,
    location: Optional[str] = Query(default=DEFAULT_LOCATION)
):
    """Get gold rate for a single carat type."""
    carat_upper = carat.upper()
    
    if carat_upper not in SUPPORTED_CARATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid carat. Must be one of: {', '.join(SUPPORTED_CARATS)}"
        )
    
    try:
        data = await get_gold_rates(location)
        
        if not data.get("success"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=data.get("error", "Failed to fetch gold rates")
            )
        
        rate_info = data["gold_rates"].get(carat_upper)
        if not rate_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rate not available for {carat_upper} gold"
            )
        
        return {
            "carat": carat_upper,
            "location": location,
            "price_per_gram": rate_info["price_per_gram"],
            "currency": rate_info["currency"],
            "unit": rate_info["unit"],
            "purity": rate_info["purity"],
            "date": data["date"],
            "scraped_at": data["scraped_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching gold rates"
        )