import json
import logging
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger("session_cache_authorizer")
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers = [stream_handler]

class UserProfileConsolidator:
    def __init__(self, default_quota_limits: Dict[str, int]):
        self.default_quota_limits = default_quota_limits

    def resolve_effective_entitlements(self, session_cache: Dict[str, Any], db_overrides: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Merging session snapshot for user: {session_cache.get('user_id')}")

        consolidated = {}
        consolidated.update(session_cache)
        consolidated.update(db_overrides)

        # Safe lookup with explicit fallback for pre-migration session caches that lack 'tier_level'
        tier = consolidated.get("tier_level")
        if tier is None:
            logger.warning(
                "tier_level missing from consolidated session — applying default tier 'BASIC'"
            )
            tier = "BASIC"

        # Warn if the resolved tier is not a recognised value in the quota table
        if tier not in self.default_quota_limits:
            logger.warning(
                f"Unrecognised tier '{tier}' — effective_limit will use default quota of 100"
            )

        limit = self.default_quota_limits.get(tier, 100)
        consolidated["effective_limit"] = limit
        return consolidated

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("Resolving user quota constraints for inbound query...")

    # Legacy cache structure (missing modern 'tier_level' attribute introduced in schema migration)
    stale_cached_session = {
        "user_id": "usr_alpha_552",
        "email": "alpha@enterprise.org",
        "created_at": 1690000000,
        "is_active": True
    }

    # Upstream database overrides with unrelated attributes
    # NOTE: Once the upstream DB source is confirmed to store tier_level as the authoritative
    # post-migration value, add "tier_level": <value_from_db> here so it correctly overrides
    # any stale or default value from the session cache.
    database_overrides = {
        "last_login": 1718002000
    }

    quota_lookup = {
        "BASIC": 50,
        "STANDARD": 250,
        "PREMIUM": 1000
    }

    consolidator = UserProfileConsolidator(default_quota_limits=quota_lookup)

    try:
        profile = consolidator.resolve_effective_entitlements(stale_cached_session, database_overrides)
    except Exception as exc:
        logger.error(f"Entitlement resolution failed: {exc}", exc_info=True)
        return {
            "statusCode": 500,
            "error": "entitlement_resolution_failed",
            "detail": str(exc)
        }

    logger.info(f"Assigned limit: {profile['effective_limit']}")
    return {"statusCode": 200, "user_profile": profile}

if __name__ == "__main__":
    lambda_handler({}, None)
