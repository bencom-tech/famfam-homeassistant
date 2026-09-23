"""DataUpdateCoordinator for the FamFam integration.

One coordinator polls GET /state with If-None-Match; a 304 is "no change",
not an error. Payload field names match the server's haData.ts shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, tzinfo
import logging
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FamFamApiClient, FamFamApiError, FamFamAuthError, FamFamConnectionError
from .const import (
    CONF_LISTS,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    STATE_MAX_AGE,
)

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
class FamFamCheckinDay:
    """One day's dinner check-ins from the state payload.

    A uid absent from responses means no answer yet; a uid absent from
    sources means a manual answer (the server's fail-open rule).
    """

    date: str
    responses: dict[str, str]
    guests: dict[str, int]
    sources: dict[str, str]


@dataclass(slots=True)
class FamFamTrip:
    """An active shopping trip from the state payload.

    The server omits already-expired trips, but a 304-quiet family keeps
    serving the cached one — readers must still check expires_at.
    """

    started_by_uid: str
    started_at: str | None
    expires_at: str
    window_minutes: int
    store_name: str | None


@dataclass(slots=True)
class FamFamRecipe:
    """A recipe hit from GET /recipes/search (dinner-sensor enrichment)."""

    id: str
    name: str
    servings: int | None
    prep_time: int | None
    cook_time: int | None


@dataclass(slots=True)
class FamFamData:
    """Parsed coordinator data."""

    state_version: int
    generated_at: str
    timezone: str
    lists: dict[str, FamFamList]
    events: list[FamFamEvent]
    meals: list[FamFamMeal]
    checkins: dict[str, FamFamCheckinDay]
    trip: FamFamTrip | None

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
        checkins = {
            day["date"]: FamFamCheckinDay(
                date=day["date"],
                responses=dict(day.get("responses") or {}),
                guests=dict(day.get("guests") or {}),
                sources=dict(day.get("sources") or {}),
            )
            for day in payload.get("checkins", [])
        }
        trip = None
        if raw_trip := payload.get("trip"):
            trip = FamFamTrip(
                started_by_uid=raw_trip.get("startedByUid", ""),
                started_at=raw_trip.get("startedAt"),
                expires_at=raw_trip.get("expiresAt", ""),
                window_minutes=raw_trip.get("windowMinutes", 0),
                store_name=raw_trip.get("storeName"),
            )
        return cls(
            state_version=payload.get("stateVersion", 0),
            generated_at=payload.get("generatedAt", ""),
            timezone=payload.get("timezone", ""),
            lists=lists,
            events=events,
            meals=meals,
            checkins=checkins,
            trip=trip,
        )


def exposed_list_ids(
    coordinator: FamFamCoordinator, entry: FamFamConfigEntry
) -> set[str]:
    """The list ids the user chose to expose as entities."""
    ids = set(coordinator.data.lists)
    # Absent key means all lists — new FamFam lists appear automatically.
    if CONF_LISTS in entry.options:
        ids &= set(entry.options[CONF_LISTS])
    return ids


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
        # Enrichment for the tonight's-dinner sensor: meals carry only a
        # recipeId, so servings/prep/cook come from a recipe search cached
        # here and refreshed only when tonight's recipe changes.
        self.tonight_recipe: FamFamRecipe | None = None
        self._enriched_recipe_id: str | None = None

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
            # Enrichment still runs: at midnight "tonight" rolls to a meal
            # already present in the unchanged payload.
            await self._async_enrich_tonights_recipe(self.data)
            return self.data
        self.etag = result.etag
        assert result.payload is not None
        data = FamFamData.from_payload(result.payload)
        await self._async_enrich_tonights_recipe(data)
        return data

    async def async_refresh_after_write(self) -> None:
        """Refresh after one of our own writes, bypassing the ETag.

        The server bumps stateVersion from a trailing task ~10s after a write,
        so an ETag'd GET straight after it 304s over stale data and the change
        only shows on the next poll. Without the ETag /state reads live. The
        delayed bump later costs one extra full fetch, never staleness.
        """
        self.etag = None
        await self.async_refresh()

    @property
    def family_tz(self) -> tzinfo:
        """The family's timezone, falling back to HA's configured zone."""
        tz_name = self.data.timezone if self.data else self.bootstrap.timezone
        if tz_name:
            try:
                return ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return dt_util.get_default_time_zone()

    def family_today(self) -> str:
        """Today's date key ("tonight") in the family's timezone."""
        return dt_util.now(self.family_tz).date().isoformat()

    async def _async_enrich_tonights_recipe(self, data: FamFamData) -> None:
        """Cache tonight's recipe details for the dinner sensor.

        Never fails the update: a broken search just leaves the attributes
        null until the next poll retries.
        """
        today = self.family_today()
        meal = next((m for m in data.meals if m.date == today), None)
        recipe_id = meal.recipe_id if meal else None
        if recipe_id == self._enriched_recipe_id:
            return
        if not recipe_id:
            self.tonight_recipe = None
            self._enriched_recipe_id = None
            return
        assert meal is not None
        try:
            recipes = await self.client.async_search_recipes(meal.meal)
        except (FamFamConnectionError, FamFamApiError) as err:
            # Leave the change guard unset so the next poll retries.
            _LOGGER.debug("Recipe search failed, will retry: %s", err)
            return
        hit = next((r for r in recipes if r.get("id") == recipe_id), None)
        # A miss (renamed meal, >50 matches) is deterministic — cache it so
        # every poll doesn't repeat the same fruitless search.
        self.tonight_recipe = (
            FamFamRecipe(
                id=recipe_id,
                name=hit.get("name", ""),
                servings=hit.get("servings"),
                prep_time=hit.get("prepTime"),
                cook_time=hit.get("cookTime"),
            )
            if hit
            else None
        )
        self._enriched_recipe_id = recipe_id
