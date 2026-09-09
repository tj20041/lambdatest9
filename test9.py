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

        # FAILS HERE: Cached session was constructed before schema migration and lacks 'tier_level'
        # Direct dictionary subscript raises KeyError: 'tier_level'
        tier = consolidated["tier_level"]
        
        limit = self.default_quota_limits.get(tier, 100)
        consolidated["effective_limit"] = limit
        return consolidated

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("Resolving user quota constraints for inbound query...")

    # Legacy cache structure (missing modern 'tier_level' attribute)
    stale_cached_session = {
        "user_id": "usr_alpha_552",
        "email": "alpha@enterprise.org",
        "created_at": 1690000000,
        "is_active": True
    }

    # Upstream database overrides with unrelated attributes
    database_overrides = {
        "last_login": 1718002000
    }

    quota_lookup = {
        "BASIC": 50,
        "STANDARD": 250,
        "PREMIUM": 1000
    }

    consolidator = UserProfileConsolidator(default_quota_limits=quota_lookup)
    profile = consolidator.resolve_effective_entitlements(stale_cached_session, database_overrides)

    logger.info(f"Assigned limit: {profile['effective_limit']}")
    return {"statusCode": 200, "user_profile": profile}

if __name__ == "__main__":
    lambda_handler({}, None)
