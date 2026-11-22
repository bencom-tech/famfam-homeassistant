"""Chores-due sensors and the import attributes on the next-event sensors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.famfam.const import CONF_LISTS

from .const import ALEX, CHORE_LIST, GROCERY_LIST, LEGACY_BOOTSTRAP, LEGACY_STATE, SAM

EntityId = Callable[[str, str], str | None]


@pytest.mark.usefixtures("init_integration")
async def test_list_sensor_counts_due_and_overdue(
    hass: HomeAssistant, entity_id: EntityId
) -> None:
    """Due today or earlier, still to do, not paused; whoever it is for."""
    state = hass.states.get(entity_id("sensor", f"chores_due_list_{CHORE_LIST}"))
    assert state.state == "2"
    assert state.attributes["overdue"] == 1
    # Oldest due date first.
    assert state.attributes["chores"] == [
        {"name": "Lawn", "due": "2026-11-20", "assignee": "Sam", "list": "Chores"},
        {"name": "Bins", "due": "2026-11-22", "assignee": "Alex", "list": "Chores"},
    ]


@pytest.mark.usefixtures("init_integration")
async def test_member_sensors_count_their_own_chores(
    hass: HomeAssistant, entity_id: EntityId
) -> None:
    """Each member sees the chores that are theirs."""
    alex = hass.states.get(entity_id("sensor", f"chores_due_member_{ALEX}"))
    assert alex.state == "1"
    assert alex.attributes["overdue"] == 0
    assert [chore["name"] for chore in alex.attributes["chores"]] == ["Bins"]

    sam = hass.states.get(entity_id("sensor", f"chores_due_member_{SAM}"))
    assert sam.state == "1"
    assert sam.attributes["overdue"] == 1


@pytest.mark.usefixtures("init_integration")
async def test_due_count_follows_the_family_date(
    hass: HomeAssistant, entity_id: EntityId, freezer: FrozenDateTimeFactory
) -> None:
    """A chore becomes due on its date with no change on the server."""
    entity = entity_id("sensor", f"chores_due_member_{ALEX}")
    # Wednesday 25 November in Brisbane: Dishes is now due, Bins is overdue.
    freezer.move_to("2026-11-25T02:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    state = hass.states.get(entity)
    assert state.state == "2"
    assert state.attributes["overdue"] == 1


async def test_no_chores_sensors_without_a_chore_list(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    state_payload: dict[str, Any],
    entity_id: EntityId,
) -> None:
    """A family that doesn't use chores gets no extra sensors."""
    state_payload["lists"] = [
        lst for lst in state_payload["lists"] if lst["id"] != CHORE_LIST
    ]
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id("sensor", f"chores_due_member_{ALEX}") is None
    assert entity_id("sensor", f"list_remaining_{GROCERY_LIST}") is not None


async def test_hiding_the_chore_list_removes_its_sensors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    entity_id: EntityId,
) -> None:
    """Chores on a list the user chose not to show don't count."""
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_LISTS: [GROCERY_LIST]}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id("todo", CHORE_LIST) is None
    assert entity_id("sensor", f"chores_due_list_{CHORE_LIST}") is None
    assert entity_id("sensor", f"chores_due_member_{ALEX}") is None


async def test_older_server_shows_chore_list_as_a_plain_list(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    entity_id: EntityId,
) -> None:
    """Against a server from before chores nothing is lost and nothing added."""
    from .const import API

    aioclient_mock.get(f"{API}/bootstrap", json=LEGACY_BOOTSTRAP)
    aioclient_mock.get(f"{API}/state", json=LEGACY_STATE, headers={"ETag": '"7"'})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id("todo", CHORE_LIST)).state == "5"
    assert entity_id("sensor", f"list_remaining_{CHORE_LIST}") is not None
    assert entity_id("sensor", f"chores_due_list_{CHORE_LIST}") is None
    assert entity_id("sensor", f"chores_due_member_{ALEX}") is None
    assert entity_id("binary_sensor", f"away_{ALEX}") is None


@pytest.mark.usefixtures("init_integration")
async def test_next_event_says_when_it_was_imported(
    hass: HomeAssistant, entity_id: EntityId, freezer: FrozenDateTimeFactory
) -> None:
    """The next-event sensors carry the import's source calendar."""
    entity = entity_id("sensor", "next_event")
    state = hass.states.get(entity)
    assert state.state == "Swimming"
    assert state.attributes["imported"] is False
    assert state.attributes["imported_from"] is None

    # After Swimming has started, the imported Dentist is next.
    freezer.move_to("2026-11-23T02:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    state = hass.states.get(entity)
    assert state.state == "Dentist"
    assert state.attributes["imported"] is True
    assert state.attributes["imported_from"] == "Work"
