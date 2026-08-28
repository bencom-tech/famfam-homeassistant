"""Binary sensor platform for the FamFam integration.

The per-member home-for-dinner sensors are the headline: no other family
integration knows who is home tonight. Plus the shopping-trip flag and a
check-ins-complete rollup for nag automations.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import (
    FamFamConfigEntry,
    FamFamCoordinator,
    FamFamMember,
    FamFamTrip,
)
from .entity import FamFamEntity

PARALLEL_UPDATES = 0

# Responses that count as "answered" for the completeness rollup.
_ANSWERED = {"eating", "no-meal"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamFamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the FamFam binary sensors."""
    coordinator = entry.runtime_data

    entities: list[FamFamEntity] = [
        FamFamShoppingTripActiveBinarySensor(coordinator),
        FamFamDinnerCheckinsCompleteBinarySensor(coordinator),
    ]
    entities.extend(
        FamFamHomeForDinnerBinarySensor(coordinator, member)
        for member in coordinator.bootstrap.members
    )

    # Remove sensors for members who left; their devices are purged in
    # __init__.py. New members appear after a reload, like the calendars.
    valid_unique_ids = {entity.unique_id for entity in entities}
    entity_registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if (
            reg_entry.domain == BINARY_SENSOR_DOMAIN
            and reg_entry.unique_id not in valid_unique_ids
        ):
            entity_registry.async_remove(reg_entry.entity_id)

    async_add_entities(entities)


class FamFamShoppingTripActiveBinarySensor(FamFamEntity, BinarySensorEntity):
    """On while someone is heading to the shops."""

    _attr_translation_key = "shopping_trip_active"

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_shopping_trip_active"
        )

    def _active_trip(self) -> FamFamTrip | None:
        """The trip, only while unexpired.

        The server omits expired trips from fresh payloads, but a quiet
        family 304s and keeps the cached one — so expiry is checked here,
        flipping the sensor off within one poll of expires_at.
        """
        trip = self.coordinator.data.trip
        if trip is None:
            return None
        expires = dt_util.parse_datetime(trip.expires_at)
        if expires is None or expires <= dt_util.utcnow():
            return None
        return trip

    @property
    def is_on(self) -> bool:
        """Whether a trip is running."""
        return self._active_trip() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Who is going and for how long; all None while off."""
        trip = self._active_trip()
        member: FamFamMember | None = None
        if trip is not None:
            member = next(
                (
                    m
                    for m in self.coordinator.bootstrap.members
                    if m.id == trip.started_by_uid
                ),
                None,
            )
        return {
            "member": member.name if member else None,
            "member_colour": member.colour if member else None,
            "started_at": trip.started_at if trip else None,
            "expires_at": trip.expires_at if trip else None,
        }


class FamFamHomeForDinnerBinarySensor(FamFamEntity, BinarySensorEntity):
    """On when this member has checked in as eating tonight."""

    _attr_translation_key = "home_for_dinner"

    def __init__(self, coordinator: FamFamCoordinator, member: FamFamMember) -> None:
        """Initialise on the member's device."""
        super().__init__(coordinator, member_id=member.id)
        self._member = member
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_home_for_dinner_{member.id}"
        )

    def _response(self) -> str | None:
        day = self.coordinator.data.checkins.get(self.coordinator.family_today())
        if day is None:
            return None
        return day.responses.get(self._member.id)

    @property
    def is_on(self) -> bool:
        """Whether the member said they're eating."""
        return self._response() == "eating"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Whether the answer was manual or from their usual week."""
        if self._response() is None:
            return {"source": None}
        day = self.coordinator.data.checkins[self.coordinator.family_today()]
        # An absent uid means a manual answer (the server's fail-open rule).
        return {"source": day.sources.get(self._member.id, "manual")}


class FamFamDinnerCheckinsCompleteBinarySensor(FamFamEntity, BinarySensorEntity):
    """On when every family member has answered for tonight."""

    _attr_translation_key = "dinner_checkins_complete"

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_dinner_checkins_complete"
        )

    def _pending(self) -> list[str]:
        day = self.coordinator.data.checkins.get(self.coordinator.family_today())
        responses = day.responses if day else {}
        return [
            member.name
            for member in self.coordinator.bootstrap.members
            if responses.get(member.id) not in _ANSWERED
        ]

    @property
    def is_on(self) -> bool:
        """Whether everyone has answered."""
        return not self._pending()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Who still hasn't answered, for nag automations (spec §5.4)."""
        return {"pending": self._pending()}
