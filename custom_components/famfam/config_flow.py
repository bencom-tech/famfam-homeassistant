"""Config flow for the FamFam integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FamFamApiClient, FamFamAuthError, FamFamConnectionError
from .const import (
    CONF_CREATE_MEMBER_CALENDARS,
    CONF_DEFAULT_MEMBER,
    CONF_LISTS,
    CONF_POLL_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

if TYPE_CHECKING:
    from .coordinator import FamFamConfigEntry

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR,
        vol.Optional(CONF_URL, default=DEFAULT_BASE_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR})


class FamFamConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the FamFam config flow."""

    VERSION = 1

    bootstrap: dict[str, Any]

    async def _async_validate(self, token: str, base_url: str) -> dict[str, str]:
        """Validate a token via GET /bootstrap; set the unique id on success."""
        errors: dict[str, str] = {}
        client = FamFamApiClient(async_get_clientsession(self.hass), token, base_url)
        try:
            self.bootstrap = await client.async_bootstrap()
        except FamFamAuthError:
            errors["base"] = "invalid_auth"
        except FamFamConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating the FamFam token")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(self.bootstrap["family"]["id"])
        return errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input.get(CONF_URL, DEFAULT_BASE_URL)
            if not (
                errors := await self._async_validate(
                    user_input[CONF_API_TOKEN], base_url
                )
            ):
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self.bootstrap["family"]["name"],
                    data={
                        CONF_API_TOKEN: user_input[CONF_API_TOKEN],
                        CONF_URL: base_url,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth after the token was revoked or expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh token and validate it against the same family."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            base_url = reauth_entry.data.get(CONF_URL, DEFAULT_BASE_URL)
            if not (
                errors := await self._async_validate(
                    user_input[CONF_API_TOKEN], base_url
                )
            ):
                self._abort_if_unique_id_mismatch(reason="unique_id_mismatch")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_API_TOKEN: user_input[CONF_API_TOKEN]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"family_name": reauth_entry.title},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> FamFamOptionsFlow:
        """Get the options flow for this handler."""
        return FamFamOptionsFlow()


class FamFamOptionsFlow(OptionsFlowWithReload):
    """Options flow; the entry reloads automatically after a save."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        entry: FamFamConfigEntry = self.config_entry
        try:
            bootstrap = entry.runtime_data.bootstrap
        except AttributeError:
            # Entry failed to set up — there is nothing to offer yet.
            return self.async_abort(reason="not_loaded")

        all_list_ids = [lst.id for lst in bootstrap.lists]

        if user_input is not None:
            user_input[CONF_POLL_INTERVAL] = int(user_input[CONF_POLL_INTERVAL])
            # "All lists selected" is stored as an absent key so lists created
            # in FamFam later appear automatically without touching options.
            if set(user_input.get(CONF_LISTS, [])) >= set(all_list_ids):
                user_input.pop(CONF_LISTS, None)
            return self.async_create_entry(data=user_input)

        options = entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(
                    CONF_DEFAULT_MEMBER,
                    description={
                        "suggested_value": options.get(CONF_DEFAULT_MEMBER)
                    },
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=member.id, label=member.name)
                            for member in bootstrap.members
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_CREATE_MEMBER_CALENDARS,
                    default=options.get(CONF_CREATE_MEMBER_CALENDARS, True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_LISTS,
                    default=options.get(CONF_LISTS, all_list_ids),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=lst.id, label=lst.name)
                            for lst in bootstrap.lists
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
