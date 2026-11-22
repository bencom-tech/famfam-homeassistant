"""Payload parsing, old and new server shapes, and the refetch rules."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.famfam.coordinator import FamFamBootstrap, FamFamData

from .conftest import calls
from .const import (
    ALEX,
    BOOTSTRAP,
    CHORE_LIST,
    GROCERY_LIST,
    LEGACY_BOOTSTRAP,
    LEGACY_STATE,
    SAM,
    STATE,
)


def test_parses_chores_imports_and_away() -> None:
    """The newer fields land on the dataclasses."""
    bootstrap = FamFamBootstrap.from_payload(BOOTSTRAP)
    assert [lst.kind for lst in bootstrap.lists] == [None, "chores"]
    assert bootstrap.has_capability("chores")
    assert bootstrap.has_capability("away")

    data = FamFamData.from_payload(STATE)
    chores = data.lists[CHORE_LIST]
    assert chores.is_chores
    assert not data.lists[GROCERY_LIST].is_chores

    lawn = chores.items["ch2"]
    assert lawn.is_chore
    assert (lawn.due_date, lawn.assignee_uid, lawn.repeats) == ("2026-11-20", SAM, True)
    assert lawn.note == "Front only"
    assert not lawn.paused

    # An any-time chore for anyone is still a chore.
    garage = chores.items["ch3"]
    assert garage.is_chore
    assert (garage.due_date, garage.assignee_uid, garage.repeats) == (None, None, False)
    assert chores.items["ch4"].paused

    milk = data.lists[GROCERY_LIST].items["g1"]
    assert not milk.is_chore
    assert milk.due_date is None

    native, imported = data.events
    assert (native.imported, native.calendar_name) == (False, None)
    assert (imported.imported, imported.calendar_name) == (True, "Work")

    assert data.away[SAM].back_on == "2026-11-25"
    assert ALEX not in data.away


def test_parses_a_server_without_the_newer_fields() -> None:
    """A payload from before chores, imports and away still parses."""
    bootstrap = FamFamBootstrap.from_payload(LEGACY_BOOTSTRAP)
    assert all(lst.kind is None for lst in bootstrap.lists)
    assert not bootstrap.has_capability("chores")
    assert not bootstrap.has_capability("away")

    data = FamFamData.from_payload(LEGACY_STATE)
    assert not any(lst.is_chores for lst in data.lists.values())
    assert not any(
        item.is_chore for lst in data.lists.values() for item in lst.items.values()
    )
    assert not any(event.imported for event in data.events)
    assert data.away == {}


def test_a_chore_without_repeats_is_assumed_to_repeat() -> None:
    """The first chores release sent dueDate and assigneeUid only."""
    payload: dict[str, Any] = {
        "lists": [
            {
                "id": CHORE_LIST,
                "kind": "chores",
                "items": [{"id": "ch1", "dueDate": None, "assigneeUid": None}],
            }
        ]
    }
    item = FamFamData.from_payload(payload).lists[CHORE_LIST].items["ch1"]
    assert item.is_chore
    assert item.repeats


@pytest.mark.usefixtures("init_integration")
async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The entry loads against the mocked API and unloads cleanly."""
    assert config_entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_polls_with_the_etag_until_an_away_lapses(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    state_payload: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A dated away ending is the one change the server never signals."""
    state_payload["away"] = [{"memberId": SAM, "backOn": "2026-11-23"}]
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data

    async def _poll() -> dict[str, str]:
        mock_api.mock_calls.clear()
        freezer.tick(timedelta(seconds=61))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        (call,) = calls(mock_api, "GET", "/state")
        return call[3]

    assert (await _poll())["If-None-Match"] == '"7"'
    assert coordinator.away_member_ids() == {SAM}

    # Just past midnight on the 23rd in Brisbane, the morning Sam is back. The
    # cached payload still lists the away, so the ETag is dropped once...
    freezer.move_to("2026-11-22T15:00:00+00:00")
    assert "If-None-Match" not in await _poll()
    # ...and Sam reads as back even though this mocked server still lists it.
    assert coordinator.away_member_ids() == set()
    # Once per payload, not on every poll.
    assert (await _poll())["If-None-Match"] == '"7"'
