"""Diagnostics support for the FamFam integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import FamFamConfigEntry

# The token plus names and free text. Ids stay so membership and list
# problems remain debuggable.
TO_REDACT = {
    CONF_API_TOKEN,
    "family_name",
    "initials",
    "location",
    "meal",
    "name",
    "notes",
    "store_name",
    "text",
    "title",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FamFamConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data: dict[str, Any] = {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "bootstrap": asdict(coordinator.bootstrap),
        "etag": coordinator.etag,
        "lists": {
            list_id: asdict(famfam_list)
            for list_id, famfam_list in coordinator.data.lists.items()
        },
        "events": [asdict(event) for event in coordinator.data.events],
        "meals": [asdict(meal) for meal in coordinator.data.meals],
        "checkins": [asdict(day) for day in coordinator.data.checkins.values()],
        "trip": asdict(trip) if (trip := coordinator.data.trip) else None,
    }
    return async_redact_data(data, TO_REDACT)
