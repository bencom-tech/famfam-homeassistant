"""Button platform for the FamFam integration.

One button: announce "heading to the shops". Small, but it's a one-tap
control on a kitchen touchscreen.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.ulid import ulid_now

from .api import FamFamApiError
from .coordinator import FamFamConfigEntry, FamFamCoordinator
from .entity import FamFamEntity
from .util import api_error

# A single entity against a cloud API that tolerates concurrent calls — the
# same setting as the other mutation platforms.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamFamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the FamFam button."""
    async_add_entities([FamFamHeadingToTheShopsButton(entry.runtime_data)])


class FamFamHeadingToTheShopsButton(FamFamEntity, ButtonEntity):
    """Announce a shopping trip to the family."""

    _attr_translation_key = "heading_to_the_shops"

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_heading_to_the_shops"
        )

    async def async_press(self) -> None:
        """Start a trip as the token's member, with the server's default window.

        A fresh requestId per press: the id exists to dedupe transport
        retries of one request, and reusing it would collapse a deliberate
        second press into a silent idempotent no-op — a fresh id gets the
        server's 409 and a clear "already running" message instead.
        """
        try:
            await self.coordinator.client.async_start_trip(ulid_now())
        except FamFamApiError as err:
            # Plus-gating and "already running" get dedicated messages.
            raise api_error("trip_start_failed", err) from err
        finally:
            # Success shows the trip sensor within this refresh; a 409 against
            # a stale local view heals the same way.
            await self.coordinator.async_refresh_after_write()
