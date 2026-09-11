import json
import logging
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger("session_cache_authorizer")
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.handlers = [stream_handler]

# Default tier applied to legacy session cache entries that predate the
# schema migration which introduced 'tier_level'. Must be a key present in
# the quota_lookup table so behaviour is deterministic (maps to 50, not the
# unrelated fallback of 100 used inside resolve_effective_entitlements).
DEFAULT_TIER = "BASIC"


class UserProfileConsolidator:
    def __init__(self, default_quota_limits: Dict[str, int]):
        self.default_quota_limits = default_quota_limits

    def resolve_effective_entitlements(self, session_cache: Dict[str, Any], db_overrides: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Merging session snapshot for user: {session_cache.get('user_id')}")

        consolidated = {}
        consolidated.update(session_cache)
        consolidated.update(db_overrides)

        # Legacy cached sessions constructed before the schema migration may
        # lack 'tier_level'. Use .get() with an explicit default instead of a
        # direct subscript so missing keys degrade gracefully instead of
        # raising KeyError and terminating the Lambda invocation.
        tier = consolidated.get("tier_level", DEFAULT_TIER)
        if "tier_level" not in consolidated:
            logger.warning(
                f"tier_level missing for user {consolidated.get('user_id')}; "
                f"defaulting to '{DEFAULT_TIER}' tier"
            )

        limit = self.default_quota_limits.get(tier, 100)
        consolidated["tier_level"] = tier
        consolidated["effective_limit"] = limit
        return consolidated


def _normalize_legacy_session(session_cache: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill legacy session cache entries with a sane default tier_level
    before they are handed to the consolidator, so legacy cache entries are
    corrected at ingestion rather than relying solely on downstream
    defaulting inside resolve_effective_entitlements.
    """
    session_cache.setdefault("tier_level", DEFAULT_TIER)
    return session_cache


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("Resolving user quota constraints for inbound query...")

    # Legacy cache structure (missing modern 'tier_level' attribute)
    stale_cached_session = {
        "user_id": "usr_alpha_552",
        "email": "alpha@enterprise.org",
        "created_at": 1690000000,
        "is_active": True
    }

    # Normalize/backfill legacy session objects before resolving
    # entitlements so missing 'tier_level' entries do not propagate an
    # uncaught KeyError.
    stale_cached_session = _normalize_legacy_session(stale_cached_session)

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

    try:
        profile = consolidator.resolve_effective_entitlements(stale_cached_session, database_overrides)
    except KeyError as exc:
        logger.warning(f"Failed to resolve entitlements due to missing key {exc}; returning degraded profile")
        fallback_profile = dict(stale_cached_session)
        fallback_profile["tier_level"] = DEFAULT_TIER
        fallback_profile["effective_limit"] = quota_lookup.get(DEFAULT_TIER, 100)
        return {"statusCode": 200, "user_profile": fallback_profile, "degraded": True}

    logger.info(f"Assigned limit: {profile['effective_limit']}")
    return {"statusCode": 200, "user_profile": profile}


if __name__ == "__main__":
    lambda_handler({}, None)
