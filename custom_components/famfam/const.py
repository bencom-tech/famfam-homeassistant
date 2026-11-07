"""Constants for the FamFam integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "famfam"

DEFAULT_BASE_URL: Final = "https://famfam.life"

CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_DEFAULT_MEMBER: Final = "default_member"
CONF_CREATE_MEMBER_CALENDARS: Final = "create_member_calendars"
CONF_LISTS: Final = "lists"

DEFAULT_POLL_INTERVAL: Final = 60
MIN_POLL_INTERVAL: Final = 30
MAX_POLL_INTERVAL: Final = 300

# Shown length of timed events that have no end time (CalendarEvent needs
# end > start). A write guard keeps the synthetic end from being persisted.
EVENT_DEFAULT_DURATION: Final = timedelta(minutes=60)

# The state ETag is the family's stateVersion, so a quiet family would 304
# forever while the served event/meal windows never slide. Drop the ETag once
# the cached payload is this old to force one full refetch.
STATE_MAX_AGE: Final = timedelta(hours=24)

SERVICE_ADD_EVENT: Final = "add_event"
SERVICE_SET_DINNER_CHECKIN: Final = "set_dinner_checkin"
SERVICE_SET_MEAL: Final = "set_meal"
SERVICE_ADD_MEAL_INGREDIENTS_TO_LIST: Final = "add_meal_ingredients_to_list"
SERVICE_ADD_LIST_ITEM: Final = "add_list_item"
SERVICE_START_SHOPPING_TRIP: Final = "start_shopping_trip"
SERVICE_END_SHOPPING_TRIP: Final = "end_shopping_trip"
SERVICE_SEARCH_RECIPES: Final = "search_recipes"
SERVICE_GET_MEAL_PLAN: Final = "get_meal_plan"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_SUMMARY: Final = "summary"
ATTR_DESCRIPTION: Final = "description"
ATTR_START: Final = "start"
ATTR_END: Final = "end"
ATTR_ALL_DAY: Final = "all_day"
ATTR_MEMBERS: Final = "members"
ATTR_CALENDAR_ENTITY_ID: Final = "calendar_entity_id"
ATTR_MEMBER: Final = "member"
ATTR_DATE: Final = "date"
ATTR_STATUS: Final = "status"
ATTR_RECIPE_ID: Final = "recipe_id"
ATTR_MEAL_NAME: Final = "meal_name"
ATTR_DATE_FROM: Final = "date_from"
ATTR_DATE_TO: Final = "date_to"
ATTR_LIST_ENTITY_ID: Final = "list_entity_id"
ATTR_ITEM: Final = "item"
ATTR_CATEGORY: Final = "category"
ATTR_QUERY: Final = "query"
ATTR_CUISINE: Final = "cuisine"
ATTR_DIET: Final = "diet"
ATTR_FREE_FROM: Final = "free_from"
ATTR_COURSE: Final = "course"
ATTR_LIMIT: Final = "limit"
ATTR_DAYS: Final = "days"

# Server-side cap on the ingredients-to-list date range (haMutationsData.ts).
INGREDIENTS_RANGE_MAX_DAYS: Final = 31

# API error codes that get a dedicated message instead of the generic
# "({code})" one. Shared by the services and every mutating platform.
API_ERROR_KEYS: Final[dict[str, str]] = {
    "plus_required": "trip_plus_required",
    "trip_active": "trip_already_active",
    "organiser_only": "checkin_organiser_only",
    "event_quota": "event_quota_exceeded",
    "not_event_creator": "event_not_creator",
    "item_limit": "item_limit_reached",
    "no_list_access": "no_list_access",
    "unknown_member": "member_not_found_server",
    "rate_limited": "rate_limited",
}
