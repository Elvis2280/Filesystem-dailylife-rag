"""Shared API-key validation for HTTP and WebSocket clients."""

import secrets

from app.core.config import settings


def is_api_key_valid(candidate: str | None) -> bool:
    """Return whether a client API key is valid for the current environment.

    An unset key keeps local development backward-compatible by disabling
    authentication. When configured, comparison is constant-time.
    """
    configured_key = settings.API_KEY
    if not configured_key:
        return True
    if candidate is None:
        return False
    return secrets.compare_digest(candidate, configured_key)
