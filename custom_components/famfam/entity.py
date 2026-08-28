"""Base entity for the FamFam integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FamFamCoordinator


class FamFamEntity(CoordinatorEntity[FamFamCoordinator]):
    """Base class for FamFam entities.

    Attaches to the family hub device, or to a member device when member_id
    is given. Both are registered eagerly in __init__.py; this DeviceInfo
    carries only the identifier so the registry entries merge.
    """

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FamFamCoordinator, member_id: str | None = None
    ) -> None:
        """Initialise and attach to the hub or a member device."""
        super().__init__(coordinator)
        family_id = coordinator.bootstrap.family_id
        identifier = f"{family_id}_{member_id}" if member_id else family_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
        )
