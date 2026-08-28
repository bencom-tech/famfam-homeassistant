"""The FamFam integration."""

from __future__ import annotations

from homeassistant.const import CONF_API_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.typing import ConfigType

from .api import FamFamApiClient
from .const import DEFAULT_BASE_URL, DOMAIN
from .coordinator import FamFamConfigEntry, FamFamCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.TODO,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the famfam services (they exist even with no entry loaded)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FamFamConfigEntry) -> bool:
    """Set up FamFam from a config entry."""
    client = FamFamApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_TOKEN],
        entry.data.get(CONF_URL, DEFAULT_BASE_URL),
    )
    coordinator = FamFamCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    _async_register_devices(hass, entry, coordinator)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


@callback
def _async_register_devices(
    hass: HomeAssistant, entry: FamFamConfigEntry, coordinator: FamFamCoordinator
) -> None:
    """Create the family hub and member devices; purge stale ones."""
    bootstrap = coordinator.bootstrap
    device_registry = dr.async_get(hass)

    hub_identifier = (DOMAIN, bootstrap.family_id)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={hub_identifier},
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="FamFam",
        model="Family",
        name=f"FamFam — {bootstrap.family_name}",
    )

    expected = {hub_identifier}
    for member in bootstrap.members:
        identifier = (DOMAIN, f"{bootstrap.family_id}_{member.id}")
        expected.add(identifier)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={identifier},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="FamFam",
            model="Family member",
            name=member.name,
            via_device=hub_identifier,
        )

    # Members who left the family since the last load.
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if not set(device.identifiers) & expected:
            device_registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def async_unload_entry(hass: HomeAssistant, entry: FamFamConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
