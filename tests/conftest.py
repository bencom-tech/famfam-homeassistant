"""Fixtures for the FamFam tests: a mocked FamFam API and a loaded entry."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.famfam.const import DOMAIN

from .const import API, BASE_URL, BOOTSTRAP, FAMILY_ID, NOW, STATE, TOKEN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture(autouse=True)
def frozen_now(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Pin the clock so "today" is the date the payloads were written for."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def bootstrap_payload() -> dict[str, Any]:
    """The /bootstrap body; a test may edit it before setup."""
    return deepcopy(BOOTSTRAP)


@pytest.fixture
def state_payload() -> dict[str, Any]:
    """The /state body; a test may edit it before setup."""
    return deepcopy(STATE)


@pytest.fixture
def mock_api(
    aioclient_mock: AiohttpClientMocker,
    bootstrap_payload: dict[str, Any],
    state_payload: dict[str, Any],
) -> AiohttpClientMocker:
    """Serve /bootstrap and /state from the payload fixtures.

    The bodies are built when a request arrives, not when the mock is
    registered, so a test can edit either payload before setting up.
    """

    def _serve(payload: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
        async def _respond(
            method: str, url: Any, data: Any
        ) -> AiohttpClientMockResponse:
            return AiohttpClientMockResponse(method, url, json=payload, headers=headers)

        return _respond

    aioclient_mock.get(f"{API}/bootstrap", side_effect=_serve(bootstrap_payload))
    aioclient_mock.get(
        f"{API}/state", side_effect=_serve(state_payload, {"ETag": '"7"'})
    )
    return aioclient_mock


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A FamFam config entry, added but not set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Smith",
        unique_id=FAMILY_ID,
        data={CONF_API_TOKEN: TOKEN, CONF_URL: BASE_URL},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> MockConfigEntry:
    """Set the integration up against the mocked API."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def entity_id(hass: HomeAssistant) -> Callable[[str, str], str | None]:
    """Look an entity up by platform and the unique-id part after the family id."""

    def _entity_id(platform: str, suffix: str) -> str | None:
        return er.async_get(hass).async_get_entity_id(
            platform, DOMAIN, f"{FAMILY_ID}_{suffix}"
        )

    return _entity_id


def calls(mock: AiohttpClientMocker, method: str, path: str) -> list[tuple[Any, ...]]:
    """The recorded requests to one endpoint: (method, url, body, headers)."""
    return [
        call
        for call in mock.mock_calls
        if call[0] == method and str(call[1]).split("?")[0] == f"{API}{path}"
    ]
