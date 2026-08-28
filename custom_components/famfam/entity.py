"""Base entity for the FamFam integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FamFamCoordinator


class FamFamEntity(CoordinatorEntity[FamFamCoordinator]):
    """Base class for FamFam entities attached to the family hub device.

    The hub (and member devices) are registered eagerly in __init__.py; this
    DeviceInfo carries only the identifier so the registry entries merge.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise and attach to the family hub device."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.bootstrap.family_id)},
        )
