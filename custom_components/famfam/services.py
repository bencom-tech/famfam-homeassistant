"""Services for the FamFam integration.

Registered in async_setup so they exist even while no entry is loaded (the
action-setup quality rule); each handler resolves its target entry and
validates that it is loaded. Every mutation follows the house pattern: the
API's machine-readable error code surfaces as a translated
HomeAssistantError, and the coordinator refreshes in a finally block so a
stale local view heals even on failure.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo
from typing import Any, NoReturn

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util.ulid import ulid_now

from .api import FamFamApiError
from .const import (
    ATTR_ALL_DAY,
    ATTR_CALENDAR_ENTITY_ID,
    ATTR_CATEGORY,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_COURSE,
    ATTR_CUISINE,
    ATTR_DATE,
    ATTR_DATE_FROM,
    ATTR_DATE_TO,
    ATTR_DAYS,
    ATTR_DESCRIPTION,
    ATTR_DIET,
    ATTR_END,
    ATTR_FREE_FROM,
    ATTR_ITEM,
    ATTR_LIMIT,
    ATTR_LIST_ENTITY_ID,
    ATTR_MEAL_NAME,
    ATTR_MEMBER,
    ATTR_MEMBERS,
    ATTR_QUERY,
    ATTR_RECIPE_ID,
    ATTR_START,
    ATTR_STATUS,
    ATTR_SUMMARY,
    CONF_DEFAULT_MEMBER,
    DOMAIN,
    INGREDIENTS_RANGE_MAX_DAYS,
    SERVICE_ADD_EVENT,
    SERVICE_ADD_LIST_ITEM,
    SERVICE_ADD_MEAL_INGREDIENTS_TO_LIST,
    SERVICE_END_SHOPPING_TRIP,
    SERVICE_GET_MEAL_PLAN,
    SERVICE_SEARCH_RECIPES,
    SERVICE_SET_DINNER_CHECKIN,
    SERVICE_SET_MEAL,
    SERVICE_START_SHOPPING_TRIP,
)
from .coordinator import FamFamCoordinator

# Friendlier messages for the rejections callers will actually hit. Everything
# else falls through to the calling service's generic key with the code.
_ERROR_CODE_KEYS = {
    "plus_required": "trip_plus_required",
    "trip_active": "trip_already_active",
    "organiser_only": "checkin_organiser_only",
    "event_quota": "event_quota_exceeded",
    "item_limit": "item_limit_reached",
    "no_list_access": "no_list_access",
    "unknown_member": "member_not_found_server",
    "rate_limited": "rate_limited",
}

# The checkin select offers slug values (hassfest requires slug option keys),
# but spec readers will type the wire's hyphenated forms — accept both.
_CHECKIN_STATUSES = ["eating", "no_meal", "no_response", "no-meal", "no-response"]

_ENTRY_FIELD = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

ADD_EVENT_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_SUMMARY): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_DESCRIPTION): cv.string,
        vol.Required(ATTR_START): vol.Any(cv.datetime, cv.date),
        vol.Optional(ATTR_END): vol.Any(cv.datetime, cv.date),
        vol.Optional(ATTR_ALL_DAY, default=False): cv.boolean,
        vol.Optional(ATTR_MEMBERS): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_CALENDAR_ENTITY_ID): cv.entity_id,
    }
)

SET_DINNER_CHECKIN_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Optional(ATTR_MEMBER): cv.string,
        vol.Optional(ATTR_DATE): cv.date,
        vol.Required(ATTR_STATUS): vol.In(_CHECKIN_STATUSES),
    }
)

SET_MEAL_SCHEMA = vol.All(
    vol.Schema(
        {
            **_ENTRY_FIELD,
            vol.Required(ATTR_DATE): cv.date,
            vol.Exclusive(ATTR_RECIPE_ID, "meal"): cv.string,
            vol.Exclusive(ATTR_MEAL_NAME, "meal"): vol.All(
                cv.string, vol.Length(min=1)
            ),
        }
    ),
    cv.has_at_least_one_key(ATTR_RECIPE_ID, ATTR_MEAL_NAME),
)

ADD_MEAL_INGREDIENTS_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_DATE_FROM): cv.date,
        vol.Optional(ATTR_DATE_TO): cv.date,
        vol.Optional(ATTR_LIST_ENTITY_ID): cv.entity_id,
    }
)

ADD_LIST_ITEM_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_LIST_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_ITEM): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_CATEGORY): cv.string,
    }
)

TRIP_SCHEMA = vol.Schema(_ENTRY_FIELD)

SEARCH_RECIPES_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Optional(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_CUISINE): cv.string,
        vol.Optional(ATTR_DIET): cv.string,
        vol.Optional(ATTR_FREE_FROM): cv.string,
        vol.Optional(ATTR_COURSE): cv.string,
        vol.Optional(ATTR_LIMIT, default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=50)
        ),
    }
)

GET_MEAL_PLAN_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Optional(ATTR_DAYS, default=7): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=14)
        ),
    }
)


def _validation_error(
    key: str, placeholders: dict[str, str] | None = None
) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
    )


def _raise_write_error(default_key: str, err: FamFamApiError) -> NoReturn:
    """Surface an API rejection as a translated HomeAssistantError."""
    key = _ERROR_CODE_KEYS.get(err.code, default_key)
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=(
            {"code": err.code} if key == default_key else None
        ),
    ) from err


def _famfam_registry_entry(
    hass: HomeAssistant, entity_id: str, expected_domain: str
) -> er.RegistryEntry:
    """The registry entry for a FamFam entity of the expected domain."""
    reg_entry = er.async_get(hass).async_get(entity_id)
    if (
        reg_entry is None
        or reg_entry.platform != DOMAIN
        or reg_entry.domain != expected_domain
        or reg_entry.config_entry_id is None
    ):
        raise _validation_error("entity_not_famfam", {"entity_id": entity_id})
    return reg_entry


def _get_coordinator(
    call: ServiceCall, reg_entry: er.RegistryEntry | None = None
) -> FamFamCoordinator:
    """Resolve the target entry: entity > explicit config_entry_id > sole entry.

    An entity pins down the family being acted on, so it wins; an explicit
    config_entry_id that names a different entry is a caller mistake and is
    rejected rather than silently ignored.
    """
    hass = call.hass
    explicit: str | None = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if reg_entry is not None:
        if explicit is not None and explicit != reg_entry.config_entry_id:
            raise _validation_error("service_entry_mismatch")
        entry = hass.config_entries.async_get_entry(reg_entry.config_entry_id)
    elif explicit is not None:
        entry = hass.config_entries.async_get_entry(explicit)
        if entry is None or entry.domain != DOMAIN:
            raise _validation_error("service_entry_not_found")
    else:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise _validation_error("service_not_configured")
        loaded = [e for e in entries if e.state is ConfigEntryState.LOADED]
        if len(loaded) > 1:
            raise _validation_error("service_multiple_families")
        entry = loaded[0] if loaded else entries[0]
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        raise _validation_error("service_entry_not_loaded")
    return entry.runtime_data


def _resolve_member(coordinator: FamFamCoordinator, value: str) -> str:
    """A member id from an id or a (case-insensitive, unique) name."""
    wanted = value.strip()
    members = coordinator.bootstrap.members
    for member in members:
        if member.id == wanted:
            return member.id
    matches = [m for m in members if m.name.casefold() == wanted.casefold()]
    if len(matches) > 1:
        raise _validation_error("member_ambiguous", {"member": value})
    if not matches:
        raise _validation_error("member_not_found", {"member": value})
    return matches[0].id


def _resolve_list_id(
    coordinator: FamFamCoordinator, reg_entry: er.RegistryEntry
) -> str:
    """The FamFam list id behind a todo entity (unique_id: {family_id}_{list_id})."""
    family_prefix = f"{coordinator.bootstrap.family_id}_"
    list_id = reg_entry.unique_id.removeprefix(family_prefix)
    if list_id == reg_entry.unique_id or list_id not in coordinator.data.lists:
        raise _validation_error(
            "list_entity_invalid", {"entity_id": reg_entry.entity_id}
        )
    return list_id


def _grocery_list_id(coordinator: FamFamCoordinator) -> str:
    """The family's sole grocery list, for calls that don't name a list."""
    grocery_ids = [
        lst.id for lst in coordinator.bootstrap.lists if lst.is_grocery
    ]
    if len(grocery_ids) != 1:
        raise _validation_error("grocery_list_unresolved")
    return grocery_ids[0]


def _local(value: datetime, tz: tzinfo) -> datetime:
    """Family-local wall clock; a naive input is already wall-clock time."""
    return value if value.tzinfo is None else value.astimezone(tz)


async def _async_add_event(call: ServiceCall) -> None:
    """Create a single calendar event."""
    calendar_entity_id: str | None = call.data.get(ATTR_CALENDAR_ENTITY_ID)
    reg_entry = (
        _famfam_registry_entry(call.hass, calendar_entity_id, "calendar")
        if calendar_entity_id
        else None
    )
    coordinator = _get_coordinator(call, reg_entry)

    member_ids: list[str] | None = None
    if members := call.data.get(ATTR_MEMBERS):
        member_ids = [_resolve_member(coordinator, value) for value in members]
    elif reg_entry is not None:
        # {family_id}_calendar_{member_id}: a member calendar assigns to that
        # member, the family calendar to everyone; the meal-plan calendar
        # isn't an event calendar at all.
        suffix = reg_entry.unique_id.removeprefix(
            f"{coordinator.bootstrap.family_id}_calendar_"
        )
        if suffix != "family":
            if not any(
                m.id == suffix for m in coordinator.bootstrap.members
            ):
                raise _validation_error(
                    "calendar_entity_invalid",
                    {"entity_id": reg_entry.entity_id},
                )
            member_ids = [suffix]

    start: date | datetime = call.data[ATTR_START]
    end: date | datetime | None = call.data.get(ATTR_END)
    body: dict[str, Any] = {"title": call.data[ATTR_SUMMARY].strip()}
    if isinstance(start, datetime) and not call.data[ATTR_ALL_DAY]:
        # The server stores wall-clock date + HH:mm in the family zone.
        tz = coordinator.family_tz
        local_start = _local(start, tz)
        body["date"] = local_start.date().isoformat()
        body["startTime"] = local_start.strftime("%H:%M")
        if isinstance(end, datetime):
            local_end = _local(end, tz)
            if local_end < local_start:
                raise _validation_error("date_range_invalid")
            if local_end.date() != local_start.date():
                raise _validation_error("event_multi_day_not_supported")
            if (end_time := local_end.strftime("%H:%M")) != body["startTime"]:
                body["endTime"] = end_time
        elif isinstance(end, date):
            raise _validation_error("event_multi_day_not_supported")
    else:
        tz = coordinator.family_tz
        start_date = (
            _local(start, tz).date() if isinstance(start, datetime) else start
        )
        if end is not None:
            end_date = _local(end, tz).date() if isinstance(end, datetime) else end
            if end_date < start_date:
                raise _validation_error("date_range_invalid")
            # Accept both conventions for a one-day all-day event: the same
            # date, or calendar-style exclusive end (start + 1 day).
            if end_date - start_date > timedelta(days=1):
                raise _validation_error("event_multi_day_not_supported")
        body["date"] = start_date.isoformat()
        body["allDay"] = True
    if description := (call.data.get(ATTR_DESCRIPTION) or "").strip():
        body["notes"] = description
    if member_ids:
        body["memberIds"] = member_ids

    try:
        await coordinator.client.async_create_event(body)
    except FamFamApiError as err:
        _raise_write_error("event_create_failed", err)
    finally:
        await coordinator.async_refresh_after_write()


async def _async_set_dinner_checkin(call: ServiceCall) -> None:
    """Set a member's dinner check-in, defaulting to the default member and today."""
    coordinator = _get_coordinator(call)
    if member := call.data.get(ATTR_MEMBER):
        member_id = _resolve_member(coordinator, member)
    elif default := coordinator.config_entry.options.get(CONF_DEFAULT_MEMBER):
        member_id = default
    else:
        raise _validation_error("member_required")
    date_value: date | None = call.data.get(ATTR_DATE)
    date_key = (
        date_value.isoformat() if date_value else coordinator.family_today()
    )
    status = call.data[ATTR_STATUS].replace("_", "-")
    try:
        await coordinator.client.async_set_checkin(date_key, member_id, status)
    except FamFamApiError as err:
        _raise_write_error("checkin_set_failed", err)
    finally:
        await coordinator.async_refresh_after_write()


async def _async_set_meal(call: ServiceCall) -> None:
    """Set the planned meal for a date, by recipe or free text."""
    coordinator = _get_coordinator(call)
    date_key = call.data[ATTR_DATE].isoformat()
    try:
        await coordinator.client.async_set_meal(
            date_key,
            recipe_id=call.data.get(ATTR_RECIPE_ID),
            free_text=call.data.get(ATTR_MEAL_NAME),
        )
    except FamFamApiError as err:
        _raise_write_error("meal_set_failed", err)
    finally:
        await coordinator.async_refresh_after_write()


async def _async_add_meal_ingredients_to_list(call: ServiceCall) -> None:
    """Send planned-meal ingredients to a list (grocery list by default)."""
    list_entity_id: str | None = call.data.get(ATTR_LIST_ENTITY_ID)
    reg_entry = (
        _famfam_registry_entry(call.hass, list_entity_id, "todo")
        if list_entity_id
        else None
    )
    coordinator = _get_coordinator(call, reg_entry)
    list_id = (
        _resolve_list_id(coordinator, reg_entry)
        if reg_entry is not None
        else _grocery_list_id(coordinator)
    )
    date_from: date = call.data[ATTR_DATE_FROM]
    date_to: date = call.data.get(ATTR_DATE_TO, date_from)
    if date_to < date_from:
        raise _validation_error("date_range_invalid")
    if (date_to - date_from).days >= INGREDIENTS_RANGE_MAX_DAYS:
        raise _validation_error(
            "date_range_too_long",
            {"max_days": str(INGREDIENTS_RANGE_MAX_DAYS)},
        )
    try:
        await coordinator.client.async_add_meal_ingredients_to_list(
            date_from.isoformat(), date_to.isoformat(), list_id
        )
    except FamFamApiError as err:
        _raise_write_error("ingredients_add_failed", err)
    finally:
        await coordinator.async_refresh_after_write()


async def _async_add_list_item(call: ServiceCall) -> None:
    """Add an item to a list, optionally straight into an aisle category."""
    reg_entry = _famfam_registry_entry(
        call.hass, call.data[ATTR_LIST_ENTITY_ID], "todo"
    )
    coordinator = _get_coordinator(call, reg_entry)
    list_id = _resolve_list_id(coordinator, reg_entry)
    try:
        await coordinator.client.async_create_item(
            list_id,
            call.data[ATTR_ITEM].strip(),
            call.data.get(ATTR_CATEGORY),
        )
    except FamFamApiError as err:
        _raise_write_error("item_create_failed", err)
    finally:
        await coordinator.async_refresh_after_write()


async def _async_start_shopping_trip(call: ServiceCall) -> None:
    """Announce a shopping trip as the token's member.

    A fresh requestId per call, for the same reason as the button: reusing
    one would collapse a deliberate second call into a silent idempotent
    no-op instead of the server's clear "already running" 409.
    """
    coordinator = _get_coordinator(call)
    try:
        await coordinator.client.async_start_trip(ulid_now())
    except FamFamApiError as err:
        _raise_write_error("trip_start_failed", err)
    finally:
        await coordinator.async_refresh_after_write()


async def _async_end_shopping_trip(call: ServiceCall) -> None:
    """End the current shopping trip; ending none is a quiet success."""
    coordinator = _get_coordinator(call)
    try:
        await coordinator.client.async_end_trip()
    except FamFamApiError as err:
        _raise_write_error("trip_end_failed", err)
    finally:
        await coordinator.async_refresh_after_write()


async def _async_search_recipes(call: ServiceCall) -> ServiceResponse:
    """Search the family's recipes and return the hits."""
    coordinator = _get_coordinator(call)
    try:
        recipes = await coordinator.client.async_search_recipes(
            call.data.get(ATTR_QUERY, ""),
            cuisine=call.data.get(ATTR_CUISINE),
            diet=call.data.get(ATTR_DIET),
            free_from=call.data.get(ATTR_FREE_FROM),
            course=call.data.get(ATTR_COURSE),
        )
    except FamFamApiError as err:
        _raise_write_error("recipe_search_failed", err)
    limited = recipes[: call.data[ATTR_LIMIT]]
    return {
        "count": len(limited),
        "recipes": [
            {
                "id": recipe.get("id"),
                "name": recipe.get("name"),
                "cuisine": recipe.get("cuisine"),
                "courses": recipe.get("courses"),
                "suitable_for_diet": recipe.get("suitableForDiet"),
                "allergen_free": recipe.get("allergenFree"),
                "servings": recipe.get("servings"),
                "prep_time_minutes": recipe.get("prepTime"),
                "cook_time_minutes": recipe.get("cookTime"),
                "rating": recipe.get("rating"),
                "starred": recipe.get("starred"),
                "ingredients": recipe.get("ingredients"),
            }
            for recipe in limited
        ],
    }


async def _async_get_meal_plan(call: ServiceCall) -> ServiceResponse:
    """The meal plan from today, straight from coordinator data.

    There is no dedicated endpoint — /state already serves a 14-day window,
    which is why days is capped at 14.
    """
    coordinator = _get_coordinator(call)
    today = date.fromisoformat(coordinator.family_today())
    last = today + timedelta(days=call.data[ATTR_DAYS] - 1)
    member_names = {m.id: m.name for m in coordinator.bootstrap.members}
    meals = [
        {
            "date": meal.date,
            "meal": meal.meal,
            "recipe_id": meal.recipe_id,
            "cook": member_names.get(meal.cook_uid) if meal.cook_uid else None,
            "ingredient_status": meal.ingredient_status,
        }
        for meal in sorted(coordinator.data.meals, key=lambda m: m.date)
        if meal.meal and today <= date.fromisoformat(meal.date) <= last
    ]
    return {"meals": meals}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the famfam services."""
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_EVENT, _async_add_event, schema=ADD_EVENT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DINNER_CHECKIN,
        _async_set_dinner_checkin,
        schema=SET_DINNER_CHECKIN_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_MEAL, _async_set_meal, schema=SET_MEAL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_MEAL_INGREDIENTS_TO_LIST,
        _async_add_meal_ingredients_to_list,
        schema=ADD_MEAL_INGREDIENTS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_LIST_ITEM,
        _async_add_list_item,
        schema=ADD_LIST_ITEM_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_SHOPPING_TRIP,
        _async_start_shopping_trip,
        schema=TRIP_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_END_SHOPPING_TRIP,
        _async_end_shopping_trip,
        schema=TRIP_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_RECIPES,
        _async_search_recipes,
        schema=SEARCH_RECIPES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MEAL_PLAN,
        _async_get_meal_plan,
        schema=GET_MEAL_PLAN_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
