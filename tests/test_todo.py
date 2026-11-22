"""Chore lists as to-do entities."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import calls
from .const import API, CHORE_LIST, GROCERY_LIST

pytestmark = pytest.mark.usefixtures("init_integration")

EntityId = Callable[[str, str], str | None]


async def _items(hass: HomeAssistant, entity: str) -> dict[str, dict[str, Any]]:
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": entity, "status": ["needs_action", "completed"]},
        blocking=True,
        return_response=True,
    )
    return {item["uid"]: item for item in response[entity]["items"]}


async def test_chore_list_shows_due_dates_notes_and_assignees(
    hass: HomeAssistant, entity_id: EntityId
) -> None:
    """A chore list carries what makes its items chores."""
    entity = entity_id("todo", CHORE_LIST)
    assert entity is not None
    state = hass.states.get(entity)
    # Unchecked chores, whatever their due date.
    assert state.state == "5"
    assert state.attributes["item_assignees"] == {
        "ch1": "Alex",
        "ch2": "Sam",
        "ch4": "Alex",
        "ch5": "Alex",
        "ch6": "Alex",
    }
    assert state.attributes["paused_items"] == ["ch4"]

    items = await _items(hass, entity)
    assert items["ch1"]["due"] == "2026-11-22"
    assert items["ch2"]["due"] == "2026-11-20"
    assert items["ch2"]["description"] == "Front only"
    assert "due" not in items["ch3"]
    assert items["ch6"]["status"] == "completed"


async def test_plain_list_gains_no_chore_attributes(
    hass: HomeAssistant, entity_id: EntityId
) -> None:
    """A grocery list is unchanged."""
    entity = entity_id("todo", GROCERY_LIST)
    assert entity is not None
    attributes = hass.states.get(entity).attributes
    assert "item_assignees" not in attributes
    assert "paused_items" not in attributes
    assert attributes["item_categories"] == {"g1": "Dairy"}
    assert "due" not in (await _items(hass, entity))["g1"]


@pytest.mark.parametrize(
    ("item", "extra_fetches"),
    [
        # Repeating: the server rolls it on ~10s later, so look again.
        ("ch1", 1),
        # One-off: it just stays ticked.
        ("ch3", 0),
    ],
)
async def test_ticking_a_chore(
    hass: HomeAssistant,
    entity_id: EntityId,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    item: str,
    extra_fetches: int,
) -> None:
    """Ticking sends only the tick; a repeating chore gets a second look."""
    mock_api.patch(f"{API}/lists/{CHORE_LIST}/items/{item}", json={"id": item})
    mock_api.mock_calls.clear()
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": entity_id("todo", CHORE_LIST),
            "item": item,
            "status": "completed",
        },
        blocking=True,
    )
    (patch,) = calls(mock_api, "PATCH", f"/lists/{CHORE_LIST}/items/{item}")
    assert patch[2] == {"checked": True}
    # The refresh straight after the write reads live, without the ETag.
    (fetch,) = calls(mock_api, "GET", "/state")
    assert "If-None-Match" not in fetch[3]

    mock_api.mock_calls.clear()
    freezer.tick(timedelta(seconds=16))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(calls(mock_api, "GET", "/state")) == extra_fetches


async def test_ticking_a_grocery_item_schedules_nothing(
    hass: HomeAssistant,
    entity_id: EntityId,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Plain items have no settle step to wait for."""
    mock_api.patch(f"{API}/lists/{GROCERY_LIST}/items/g1", json={"id": "g1"})
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": entity_id("todo", GROCERY_LIST),
            "item": "g1",
            "status": "completed",
        },
        blocking=True,
    )
    mock_api.mock_calls.clear()
    freezer.tick(timedelta(seconds=16))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert calls(mock_api, "GET", "/state") == []
