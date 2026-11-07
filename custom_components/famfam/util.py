"""Shared helpers for the FamFam integration."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .api import FamFamApiError
from .const import API_ERROR_KEYS, DOMAIN


def api_error(default_key: str, err: FamFamApiError) -> HomeAssistantError:
    """Map an API rejection onto a translated HomeAssistantError.

    Codes in API_ERROR_KEYS get a dedicated message; anything else falls
    through to the caller's generic key, which carries the code.
    """
    key = API_ERROR_KEYS.get(err.code, default_key)
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=(
            {"code": err.code} if key == default_key else None
        ),
    )
