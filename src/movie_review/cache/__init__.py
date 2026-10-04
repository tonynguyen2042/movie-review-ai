"""Cache identity and safe lookup/invalidation (T008)."""

from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.cache.manager import CacheManager

__all__ = ["CacheManager", "CacheSpec", "cache_key"]
