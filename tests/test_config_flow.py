"""The config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.famfam.const import DOMAIN

from .const import API, BASE_URL, FAMILY_ID, TOKEN


async def test_user_flow_creates_an_entry(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """A good token sets the family up."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: TOKEN, CONF_URL: BASE_URL}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_TOKEN] == TOKEN
    assert result["result"].unique_id == FAMILY_ID


async def test_user_flow_reports_a_rejected_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 keeps the form open with an error."""
    aioclient_mock.get(
        f"{API}/bootstrap",
        status=401,
        json={"error": {"code": "invalid_auth", "message": "Bad token."}},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "nope", CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_aborts_for_a_family_already_set_up(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> None:
    """One entry per family."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: TOKEN, CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
