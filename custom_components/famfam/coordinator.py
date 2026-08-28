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
from homeassistant.util import dt as dt_util

from .api import FamFamApiClient, FamFamApiError, FamFamAuthError, FamFamConnectionError
from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN, STATE_MAX_AGE

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
class FamFamEvent:
    """A calendar event occurrence from the state payload.

    Repeating events arrive server-expanded: beyond the first occurrence the
    id is the synthetic "{masterId}::{date}"; writes must use master_id.
    An empty member_ids means the whole family. For all-day events start is
    "YYYY-MM-DD" and the wire end just echoes date; for timed events start is
    ISO 8601 with the family's UTC offset and end may be null (no end time).
    """

    id: str
    master_id: str
    title: str
    date: str
    all_day: bool
    start: str
    end: str | None
    member_ids: list[str]
    created_by: str
    location: str | None
    notes: str | None
    repeat: str


@dataclass(slots=True)
class FamFamMeal:
    """A meal-plan day from the state payload."""

    date: str
    meal: str
    recipe_id: str | None
    cook_uid: str | None
    ingredient_status: str | None


@dataclass(slots=True)
class FamFamData:
    """Parsed coordinator data.

    Lists, events and meals are typed; the raw payload is retained for the
    sensor platforms of later sessions (check-ins, trip).
    """

    state_version: int
    generated_at: str
    timezone: str
    lists: dict[str, FamFamList]
    events: list[FamFamEvent]
    meals: list[FamFamMeal]
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
        events = [
            FamFamEvent(
                id=event["id"],
                master_id=event.get("masterId", event["id"]),
                title=event.get("title", ""),
                date=event.get("date", ""),
                all_day=event.get("allDay", False),
                start=event.get("start", ""),
                end=event.get("end"),
                member_ids=list(event.get("memberIds") or []),
                created_by=event.get("createdBy", ""),
                location=event.get("location"),
                notes=event.get("notes"),
                repeat=event.get("repeat", "never"),
            )
            for event in payload.get("events", [])
        ]
        meals = [
            FamFamMeal(
                date=meal["date"],
                meal=meal.get("meal", ""),
                recipe_id=meal.get("recipeId"),
                cook_uid=meal.get("cookUid"),
                ingredient_status=meal.get("ingredientStatus"),
            )
            for meal in payload.get("meals", [])
        ]
        return cls(
            state_version=payload.get("stateVersion", 0),
            generated_at=payload.get("generatedAt", ""),
            timezone=payload.get("timezone", ""),
            lists=lists,
            events=events,
            meals=meals,
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
        if (
            self.etag
            and self.data is not None
            and (generated := dt_util.parse_datetime(self.data.generated_at))
            and dt_util.utcnow() - dt_util.as_utc(generated) > STATE_MAX_AGE
        ):
            # The ETag is the family's stateVersion, so a quiet family 304s
            # indefinitely while the served event (-7/+28 days) and meal
            # (14 days) windows never slide. Force a full refetch instead.
            self.etag = None
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
