"""The per-member away sensors."""

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

from .const import ALEX, SAM

EntityId = Callable[[str, str], str | None]


@pytest.mark.usefixtures("init_integration")
async def test_away_sensor_follows_the_back_on_date(
    hass: HomeAssistant, entity_id: EntityId, freezer: FrozenDateTimeFactory
) -> None:
    """On while away; off from the back-on date, whatever the cache says."""
    sam = entity_id("binary_sensor", f"away_{SAM}")
    alex = entity_id("binary_sensor", f"away_{ALEX}")
    assert hass.states.get(sam).state == "on"
    assert hass.states.get(sam).attributes["back_on"] == "2026-11-25"
    assert hass.states.get(alex).state == "off"
    assert hass.states.get(alex).attributes["back_on"] is None

    freezer.move_to("2026-11-25T02:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(sam).state == "off"
    assert hass.states.get(sam).attributes["back_on"] is None


async def test_open_ended_away(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    state_payload: dict[str, Any],
    entity_id: EntityId,
) -> None:
    """An away with no date stays on."""
    state_payload["away"] = [{"memberId": ALEX, "backOn": None}]
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id("binary_sensor", f"away_{ALEX}"))
    assert state.state == "on"
    assert state.attributes["back_on"] is None


async def test_no_away_sensors_without_the_capability(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    bootstrap_payload: dict[str, Any],
    entity_id: EntityId,
) -> None:
    """A server that can't serve away gets no always-off sensors."""
    bootstrap_payload["capabilities"].remove("away")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id("binary_sensor", f"away_{SAM}") is None
    assert entity_id("binary_sensor", f"home_for_dinner_{SAM}") is not None
