"""DataUpdateCoordinator for the FamFam integration.

One coordinator polls GET /state with If-None-Match; a 304 is "no change",
not an error. Payload field names match the server's haData.ts shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FamFamApiClient, FamFamApiError, FamFamAuthError, FamFamConnectionError
from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type FamFamConfigEntry = ConfigEntry[FamFamCoordinator]


@dataclass(slots=True)
class FamFamMember:
    """A family member from the bootstrap payload."""

    id: str
    name: str
    initials: str
    colour: str
    avatar_icon: str | None
    role: str


@dataclass(slots=True)
class FamFamBootstrapList:
    """A list stub from the bootstrap payload."""

    id: str
    name: str
    is_grocery: bool
    sharing: str


@dataclass(slots=True)
class FamFamBootstrap:
    """The family shape from GET /bootstrap."""

    family_id: str
    family_name: str
    region: str
    timezone: str
    tier: str
    members: list[FamFamMember]
    lists: list[FamFamBootstrapList]
    capabilities: list[str]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FamFamBootstrap:
        """Parse the bootstrap response."""
        family = payload["family"]
        return cls(
            family_id=family["id"],
            family_name=family.get("name", ""),
            region=family.get("region", ""),
            timezone=family.get("timezone", ""),
            tier=family.get("tier", "free"),
            members=[
                FamFamMember(
                    id=member["id"],
                    name=member.get("name", ""),
                    initials=member.get("initials", ""),
                    colour=member.get("colour", ""),
                    avatar_icon=member.get("avatarIcon"),
                    role=member.get("role", "member"),
                )
                for member in payload.get("members", [])
            ],
            lists=[
                FamFamBootstrapList(
                    id=lst["id"],
                    name=lst.get("name", ""),
                    is_grocery=lst.get("isGrocery", False),
                    sharing=lst.get("sharing", ""),
                )
                for lst in payload.get("lists", [])
            ],
            capabilities=list(payload.get("capabilities", [])),
        )


@dataclass(slots=True)
class FamFamItem:
    """A list item from the state payload."""

    id: str
    text: str
    checked: bool
    category: str | None
    added_by: str
    checked_by: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(slots=True)
class FamFamList:
    """A list with items from the state payload."""

    id: str
    name: str
    is_grocery: bool
    unchecked_count: int
    categories: list[str] | None
    items: dict[str, FamFamItem]


@dataclass(slots=True)
class FamFamData:
    """Parsed coordinator data.

    Only lists are typed for now; the raw payload is retained for the
    calendar/sensor platforms of later sessions.
    """

    state_version: int
    lists: dict[str, FamFamList]
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FamFamData:
        """Parse the state response."""
        lists: dict[str, FamFamList] = {}
        for lst in payload.get("lists", []):
            items = {
                item["id"]: FamFamItem(
                    id=item["id"],
                    text=item.get("text", ""),
                    checked=item.get("checked", False),
                    category=item.get("category"),
                    added_by=item.get("addedBy", ""),
                    checked_by=item.get("checkedBy"),
                    created_at=item.get("createdAt"),
                    updated_at=item.get("updatedAt"),
                )
                for item in lst.get("items", [])
            }
            lists[lst["id"]] = FamFamList(
                id=lst["id"],
                name=lst.get("name", ""),
                is_grocery=lst.get("isGrocery", False),
                unchecked_count=lst.get("uncheckedCount", 0),
                categories=lst.get("categories"),
                items=items,
            )
        return cls(
            state_version=payload.get("stateVersion", 0),
            lists=lists,
            raw=payload,
        )


class FamFamCoordinator(DataUpdateCoordinator[FamFamData]):
    """Coordinator polling GET /state for the whole family."""

    config_entry: FamFamConfigEntry
    bootstrap: FamFamBootstrap

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FamFamConfigEntry,
        client: FamFamApiClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=int(
                    entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
                )
            ),
        )
        self.client = client
        self.etag: str | None = None

    async def _async_setup(self) -> None:
        """Fetch the family shape once per (re)load."""
        try:
            payload = await self.client.async_bootstrap()
        except FamFamAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="setup_auth_failed",
            ) from err
        except (FamFamConnectionError, FamFamApiError) as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="setup_connect_failed",
            ) from err
        self.bootstrap = FamFamBootstrap.from_payload(payload)

    async def _async_update_data(self) -> FamFamData:
        """Fetch the state, honouring the ETag."""
        try:
            result = await self.client.async_get_state(self.etag)
        except FamFamAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        except (FamFamConnectionError, FamFamApiError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        if not result.changed:
            # 304 — nothing changed since the last poll. The first refresh can
            # never 304 because there is no ETag yet, so self.data is set.
            return self.data
        self.etag = result.etag
        assert result.payload is not None
        return FamFamData.from_payload(result.payload)
