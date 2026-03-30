"""
step11/killswitch.py — Global Kill Switch via AWS SSM Parameter Store

HOW IT WORKS:
─────────────
1. Reads the SSM parameter /repomind/kill_switch
2. If value == "on"  → kill switch is ACTIVE (halt all side-effects)
3. If value == "off" → normal operation
4. If SSM is unreachable → DEFAULT SAFE: assume kill switch is ON

WHEN IS IT CHECKED:
    - At the START of the worker pipeline (before any processing)
    - Before Step 8 (PR creation) — last line of defense
    - Before Step 10 (rollback) — prevent cascading rollbacks

SAFETY DESIGN:
    ┌─────────────────────────┬──────────────────────────────┐
    │ Condition               │ Behavior                     │
    ├─────────────────────────┼──────────────────────────────┤
    │ SSM value = "off"       │ Pipeline runs normally       │
    │ SSM value = "on"        │ Pipeline halts, no side fx   │
    │ SSM unreachable         │ DEFAULT SAFE → halt pipeline │
    │ SSM parameter missing   │ DEFAULT SAFE → halt pipeline │
    │ In development mode     │ Kill switch ignored (off)    │
    └─────────────────────────┴──────────────────────────────┘

USAGE:
    from step11.killswitch import is_kill_switch_enabled

    if is_kill_switch_enabled():
        return {"status": "halted", "reason": "Kill switch is ON"}

    # Or use the decorator:
    @require_kill_switch_off
    def create_pr(...):
        ...

COMMUNICATION:
─────────────
Worker (step2) calls is_kill_switch_enabled() at pipeline start.
SSM Parameter: /repomind/kill_switch (String: "on" or "off")
SRE can toggle it via AWS Console or CLI:
    aws ssm put-parameter --name "/repomind/kill_switch" --value "on" --overwrite
"""

import functools
from typing import Optional

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("step11.killswitch")

# ──────────────────────────────────────────────
# Cache to avoid hammering SSM on every call
# ──────────────────────────────────────────────
_cache: dict = {"value": None, "ttl": 0}
CACHE_TTL_SECONDS = 30  # Re-check SSM every 30 seconds


def is_kill_switch_enabled() -> bool:
    """
    Check if the global kill switch is active.

    Returns:
        True  → kill switch is ON (halt all side-effects)
        False → kill switch is OFF (normal operation)

    Safety:
        If SSM is unreachable, returns True (fail-safe).
        In development mode, always returns False.
    """
    # In development, kill switch is always off
    if settings.ENVIRONMENT == "development":
        return False

    param_name = getattr(settings, "KILL_SWITCH_PARAM", "/repomind/kill_switch")
    if not param_name:
        return False

    # Check cache
    import time
    now = time.monotonic()
    if _cache["value"] is not None and now < _cache["ttl"]:
        return _cache["value"]

    # Query SSM
    try:
        import boto3
        ssm = boto3.client("ssm", region_name=settings.AWS_REGION)
        response = ssm.get_parameter(Name=param_name)
        value = response["Parameter"]["Value"].strip().lower()

        is_on = value == "on"
        _cache["value"] = is_on
        _cache["ttl"] = now + CACHE_TTL_SECONDS

        logger.info("kill_switch_checked", param=param_name, value=value, is_on=is_on)

        # Update Prometheus metric
        try:
            from step11.metrics import metrics
            metrics.kill_switch_state.set(1 if is_on else 0)
        except Exception:
            pass

        return is_on

    except Exception as e:
        # FAIL-SAFE: if SSM is unreachable, assume kill switch is ON
        logger.error(
            "kill_switch_ssm_error",
            param=param_name,
            error=str(e),
            defaulting_to="on (fail-safe)",
        )
        _cache["value"] = True
        _cache["ttl"] = now + 5  # Retry sooner on error
        return True


def clear_cache() -> None:
    """Clear the kill switch cache. Used in tests."""
    _cache["value"] = None
    _cache["ttl"] = 0


def require_kill_switch_off(func):
    """
    Decorator that prevents function execution when kill switch is ON.

    Usage:
        @require_kill_switch_off
        def create_pr(repo, ...):
            ...

    If the kill switch is active, returns a dict with:
        {"status": "halted", "reason": "Kill switch is ON"}
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if is_kill_switch_enabled():
            logger.warning(
                "kill_switch_blocked",
                function=func.__name__,
            )
            return {
                "status": "halted",
                "reason": "Kill switch is ON — side-effects disabled",
            }
        return func(*args, **kwargs)
    return wrapper
