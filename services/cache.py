# services/cache.py
import time
from typing import Optional, Any
from functools import wraps

class SimpleCache:
    """Thread-safe in-memory cache with TTL support"""
    
    def __init__(self):
        self._cache: dict[str, tuple[Any, float]] = {}
    
    def set(self, key: str, value: Any, ttl: float):
        """Store value with expiration time"""
        expiry = time.time() + ttl
        self._cache[key] = (value, expiry)
    
    def get(self, key: str) -> Optional[Any]:
        """Retrieve value if not expired"""
        if key not in self._cache:
            return None
        
        value, expiry = self._cache[key]
        if time.time() > expiry:
            del self._cache[key]
            return None
        return value
    
    def clear(self, key: str):
        """Manually clear a cache entry"""
        self._cache.pop(key, None)

# Global cache instance
cache = SimpleCache()

def cached(ttl: float, key_prefix: str = ""):
    """Decorator for caching async function results"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator