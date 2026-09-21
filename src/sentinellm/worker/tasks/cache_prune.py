"""Periodic reclaim of expired semantic-cache rows.

Lookups already ignore entries past `SENTINEL_CACHE_TTL_SECONDS`; without this
the table (and every candidate scan's index) only ever grew.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.caching.semantic_cache import prune_expired_entries
from sentinellm.core.config import get_settings
from sentinellm.core.logging import get_logger

logger = get_logger(__name__)


async def prune_semantic_cache(session: AsyncSession) -> int:
    pruned = await prune_expired_entries(session, get_settings().cache_ttl_seconds)
    if pruned:
        logger.info("semantic_cache_pruned", entries=pruned)
    return pruned
