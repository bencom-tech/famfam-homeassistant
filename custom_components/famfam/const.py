"""Constants for the FamFam integration."""

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
