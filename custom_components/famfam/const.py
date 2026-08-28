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
