"""Editing events imported from a member's own calendar."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.components.calendar import CalendarEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import calls
from .const import API

pytestmark = pytest.mark.usefixtures("init_integration")

EntityId = Callable[[str, str], str | None]


def _family_calendar(hass: HomeAssistant, entity_id: EntityId) -> CalendarEntity:
    entity = hass.data[DATA_INSTANCES][CALENDAR_DOMAIN].get_entity(
        entity_id("calendar", "calendar_family")
    )
    assert isinstance(entity, CalendarEntity)
    return entity


def _edit(day: int, summary: str = "Dentist") -> dict[str, Any]:
    """The edit form's payload for the imported 2pm-3pm Dentist event."""
    tz = dt_util.get_time_zone("Australia/Brisbane")
    return {
        "summary": summary,
        "dtstart": datetime(2026, 11, day, 14, 0, tzinfo=tz),
        "dtend": datetime(2026, 11, day, 15, 0, tzinfo=tz),
    }


async def test_moving_an_imported_event_is_refused_before_sending(
    hass: HomeAssistant, entity_id: EntityId, mock_api: AiohttpClientMocker
) -> None:
    """The phone keeps an import on its source date, so say so up front."""
    calendar = _family_calendar(hass, entity_id)
    with pytest.raises(HomeAssistantError) as err:
        await calendar.async_update_event("imp_1", _edit(day=26))
    assert err.value.translation_key == "event_imported_date_locked"
    assert calls(mock_api, "PATCH", "/events/imp_1") == []


async def test_other_edits_to_an_imported_event_go_through(
    hass: HomeAssistant, entity_id: EntityId, mock_api: AiohttpClientMocker
) -> None:
    """Only the date is locked."""
    mock_api.patch(f"{API}/events/imp_1", json={"id": "imp_1", "changed": True})
    calendar = _family_calendar(hass, entity_id)
    await calendar.async_update_event(
        "imp_1", _edit(day=24, summary="Dentist (Dr Lee)")
    )
    (patch,) = calls(mock_api, "PATCH", "/events/imp_1")
    assert patch[2] == {"title": "Dentist (Dr Lee)"}


async def test_moving_a_native_event_is_unaffected(
    hass: HomeAssistant, entity_id: EntityId, mock_api: AiohttpClientMocker
) -> None:
    """Events made in FamFam can still be moved."""
    mock_api.patch(f"{API}/events/e1", json={"id": "e1", "changed": True})
    tz = dt_util.get_time_zone("Australia/Brisbane")
    calendar = _family_calendar(hass, entity_id)
    await calendar.async_update_event(
        "e1",
        {
            "summary": "Swimming",
            "dtstart": datetime(2026, 11, 26, 9, 0, tzinfo=tz),
            "dtend": datetime(2026, 11, 26, 10, 0, tzinfo=tz),
        },
    )
    (patch,) = calls(mock_api, "PATCH", "/events/e1")
    assert patch[2] == {"date": "2026-11-26"}


async def test_server_refusal_gets_the_same_message(
    hass: HomeAssistant, entity_id: EntityId, mock_api: AiohttpClientMocker
) -> None:
    """A server that knows an event is imported when the cache doesn't yet."""
    mock_api.patch(
        f"{API}/events/e1",
        status=403,
        json={"error": {"code": "imported_event", "message": "Imported."}},
    )
    tz = dt_util.get_time_zone("Australia/Brisbane")
    calendar = _family_calendar(hass, entity_id)
    with pytest.raises(HomeAssistantError) as err:
        await calendar.async_update_event(
            "e1",
            {
                "summary": "Swimming",
                "dtstart": datetime(2026, 11, 26, 9, 0, tzinfo=tz),
                "dtend": datetime(2026, 11, 26, 10, 0, tzinfo=tz),
            },
        )
    assert err.value.translation_key == "event_imported_date_locked"
