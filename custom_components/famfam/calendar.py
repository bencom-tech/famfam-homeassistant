"""Calendar platform for the FamFam integration.

One entity per family member (the headline feature — native card filtering
instead of the DIY input_text pattern), plus a family calendar with every
event and a read-only meal-plan calendar. Repeating events arrive from the
server pre-expanded into occurrences; writes are single events only in v1.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, NoReturn

from homeassistant.components.calendar import (
    DOMAIN as CALENDAR_DOMAIN,
    EVENT_DESCRIPTION,
    EVENT_END,
    EVENT_LOCATION,
    EVENT_RRULE,
    EVENT_START,
    EVENT_SUMMARY,
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import FamFamApiError
from .const import CONF_CREATE_MEMBER_CALENDARS, DOMAIN, EVENT_DEFAULT_DURATION
from .coordinator import (
    FamFamConfigEntry,
    FamFamCoordinator,
    FamFamEvent,
    FamFamMember,
)
from .entity import FamFamEntity

PARALLEL_UPDATES = 0

# FamFam's repeat enum rendered as informational RRULEs. Occurrences arrive
# pre-expanded, so HA never re-expands these — they exist so the frontend
# recognises a series and shows the series chooser on delete.
_REPEAT_TO_RRULE = {
    "daily": "FREQ=DAILY",
    "weekly": "FREQ=WEEKLY",
    "fortnightly": "FREQ=WEEKLY;INTERVAL=2",
    "monthly": "FREQ=MONTHLY",
}

# Friendlier messages for the two write rejections users will actually hit.
_ERROR_CODE_KEYS = {
    "event_quota": "event_quota_exceeded",
    "not_event_creator": "event_not_creator",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamFamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the family, member and meal-plan calendars."""
    coordinator = entry.runtime_data
    entities: list[FamFamBaseCalendar] = [
        FamFamFamilyCalendar(coordinator),
        FamFamMealsCalendar(coordinator),
    ]
    if entry.options.get(CONF_CREATE_MEMBER_CALENDARS, True):
        entities.extend(
            FamFamMemberCalendar(coordinator, member)
            for member in coordinator.bootstrap.members
        )

    # Remove stale calendar entities: member calendars toggled off, or
    # members who left. The options flow reloads the entry on save, so a
    # toggle takes effect immediately. Member *devices* stay — they host
    # other entities.
    valid_unique_ids = {entity.unique_id for entity in entities}
    entity_registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if (
            reg_entry.domain == CALENDAR_DOMAIN
            and reg_entry.unique_id not in valid_unique_ids
        ):
            entity_registry.async_remove(reg_entry.entity_id)

    async_add_entities(entities)


def _to_calendar_event(famfam_event: FamFamEvent) -> CalendarEvent:
    """Map a FamFam event occurrence onto HA's CalendarEvent."""
    start: date | datetime
    end: date | datetime
    if famfam_event.all_day:
        # The wire end just echoes date; HA wants an exclusive end.
        start = date.fromisoformat(famfam_event.date)
        end = start + timedelta(days=1)
    else:
        start = datetime.fromisoformat(famfam_event.start)
        parsed_end = (
            datetime.fromisoformat(famfam_event.end) if famfam_event.end else None
        )
        if parsed_end is None or parsed_end <= start:
            # No end time (or zero-length) — CalendarEvent needs end > start.
            parsed_end = start + EVENT_DEFAULT_DURATION
        end = parsed_end
    recurring = famfam_event.repeat in _REPEAT_TO_RRULE
    return CalendarEvent(
        start=start,
        end=end,
        summary=famfam_event.title,
        description=famfam_event.notes,
        location=famfam_event.location,
        # uid is always the master id — the API rejects occurrence ids.
        uid=famfam_event.master_id,
        recurrence_id=famfam_event.date if recurring else None,
        rrule=_REPEAT_TO_RRULE.get(famfam_event.repeat),
    )


def _as_datetime(value: date | datetime) -> datetime:
    """Normalise all-day dates to local midnight for comparisons."""
    if isinstance(value, datetime):
        return value
    return dt_util.start_of_local_day(value)


class FamFamBaseCalendar(FamFamEntity, CalendarEntity):
    """Shared read side for all FamFam calendars."""

    def _calendar_events(self) -> list[CalendarEvent]:
        """This calendar's events, mapped from coordinator data."""
        raise NotImplementedError

    @property
    def event(self) -> CalendarEvent | None:
        """The in-progress event while one runs, else the next upcoming."""
        now = dt_util.now()
        unfinished = [
            calendar_event
            for calendar_event in self._calendar_events()
            if _as_datetime(calendar_event.end) > now
        ]
        if not unfinished:
            return None
        return min(unfinished, key=lambda ce: _as_datetime(ce.start))

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Events overlapping the range.

        The server serves a bounded window (events 7 days back to 28 days
        forward, meals 14 days) — ranges beyond it return what's available.
        """
        return [
            calendar_event
            for calendar_event in self._calendar_events()
            if _as_datetime(calendar_event.start) < end_date
            and _as_datetime(calendar_event.end) > start_date
        ]


class FamFamWritableCalendar(FamFamBaseCalendar):
    """Shared write side for the family and member calendars."""

    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )

    def _create_member_ids(self) -> list[str] | None:
        """Who a created event is assigned to; None means everyone."""
        return None

    def _find_event(self, uid: str) -> FamFamEvent:
        for famfam_event in self.coordinator.data.events:
            if famfam_event.master_id == uid:
                return famfam_event
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="event_not_found"
        )

    @staticmethod
    def _write_error(default_key: str, err: FamFamApiError) -> HomeAssistantError:
        key = _ERROR_CODE_KEYS.get(err.code, default_key)
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=(
                {"code": err.code} if key == default_key else None
            ),
        )

    @staticmethod
    def _raise(key: str) -> NoReturn:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key=key)

    async def async_create_event(self, **kwargs: Any) -> None:
        """Create a single event (repeats can't be created from HA in v1)."""
        if kwargs.get(EVENT_RRULE):
            self._raise("event_recurrence_not_supported")
        dtstart = kwargs[EVENT_START]
        dtend = kwargs[EVENT_END]
        body: dict[str, Any] = {"title": kwargs[EVENT_SUMMARY]}
        if isinstance(dtstart, datetime):
            # The server stores wall-clock date + HH:mm in the family zone.
            tz = self.coordinator.family_tz
            local_start = dtstart.astimezone(tz)
            local_end = dtend.astimezone(tz)
            if local_end.date() != local_start.date():
                self._raise("event_multi_day_not_supported")
            body["date"] = local_start.date().isoformat()
            body["startTime"] = local_start.strftime("%H:%M")
            if (end_time := local_end.strftime("%H:%M")) != body["startTime"]:
                body["endTime"] = end_time
        else:
            if dtend - dtstart > timedelta(days=1):
                self._raise("event_multi_day_not_supported")
            body["date"] = dtstart.isoformat()
            body["allDay"] = True
        if description := (kwargs.get(EVENT_DESCRIPTION) or "").strip():
            body["notes"] = description
        if location := (kwargs.get(EVENT_LOCATION) or "").strip():
            body["location"] = location
        if member_ids := self._create_member_ids():
            body["memberIds"] = member_ids
        try:
            await self.coordinator.client.async_create_event(body)
        except FamFamApiError as err:
            raise self._write_error("event_create_failed", err) from err
        finally:
            await self.coordinator.async_refresh()

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """PATCH only the fields that changed (data-loss guard)."""
        if recurrence_id or recurrence_range:
            self._raise("event_occurrence_not_supported")
        current = self._find_event(uid)
        if current.repeat != "never":
            # The edit form prefills from the clicked occurrence; diffing it
            # against the master would silently move the series anchor.
            self._raise("event_recurring_edit_not_supported")
        if event.get(EVENT_RRULE):
            self._raise("event_recurrence_not_supported")
        changes = self._diff_event(current, event)
        if not changes:
            return
        try:
            await self.coordinator.client.async_update_event(uid, changes)
        except FamFamApiError as err:
            raise self._write_error("event_update_failed", err) from err
        finally:
            await self.coordinator.async_refresh()

    def _diff_event(
        self, current: FamFamEvent, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the PATCH body: absent = untouched, null = clear.

        memberIds is never sent — editing an event via a member calendar
        must not re-assign it.
        """
        changes: dict[str, Any] = {}
        summary = event.get(EVENT_SUMMARY)
        if summary is not None and summary != current.title:
            changes["title"] = summary

        dtstart = event.get(EVENT_START)
        dtend = event.get(EVENT_END)
        if isinstance(dtstart, datetime):
            tz = self.coordinator.family_tz
            local_start = dtstart.astimezone(tz)
            local_end = dtend.astimezone(tz) if isinstance(dtend, datetime) else None
            start_time = local_start.strftime("%H:%M")

            # Synthetic-end guard: an event with no end time is shown with a
            # default duration; if the incoming end still matches it, the
            # user didn't touch the end, so don't persist the synthetic one.
            current_open_ended = current.all_day is False and (
                not current.end
                or datetime.fromisoformat(current.end)
                <= datetime.fromisoformat(current.start)
            )
            if (
                current_open_ended
                and local_end is not None
                and local_end - local_start == EVENT_DEFAULT_DURATION
            ):
                local_end = None

            if local_end is not None and local_end.date() != local_start.date():
                self._raise("event_multi_day_not_supported")
            if (new_date := local_start.date().isoformat()) != current.date:
                changes["date"] = new_date
            if current.all_day:
                # allDay: false is required — the server derives all-day
                # from the flag OR a missing startTime.
                changes["allDay"] = False
                changes["startTime"] = start_time
                if (
                    local_end is not None
                    and (end_time := local_end.strftime("%H:%M")) != start_time
                ):
                    changes["endTime"] = end_time
            else:
                current_start = datetime.fromisoformat(current.start).astimezone(tz)
                if start_time != current_start.strftime("%H:%M"):
                    changes["startTime"] = start_time
                if local_end is not None:
                    end_time = local_end.strftime("%H:%M")
                    current_end_time = (
                        datetime.fromisoformat(current.end)
                        .astimezone(tz)
                        .strftime("%H:%M")
                        if current.end and not current_open_ended
                        else None
                    )
                    if end_time != current_end_time and end_time != start_time:
                        changes["endTime"] = end_time
        elif isinstance(dtstart, date):
            if isinstance(dtend, date) and dtend - dtstart > timedelta(days=1):
                self._raise("event_multi_day_not_supported")
            if (new_date := dtstart.isoformat()) != current.date:
                changes["date"] = new_date
            if not current.all_day:
                changes["allDay"] = True
                changes["startTime"] = None
                changes["endTime"] = None

        if EVENT_DESCRIPTION in event:
            new_notes = (event[EVENT_DESCRIPTION] or "").strip() or None
            if new_notes != current.notes:
                changes["notes"] = new_notes
        if EVENT_LOCATION in event:
            new_location = (event[EVENT_LOCATION] or "").strip() or None
            if new_location != current.location:
                changes["location"] = new_location
        return changes

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event; for a series, only "all events" is supported."""
        if recurrence_id or recurrence_range:
            self._raise("event_occurrence_not_supported")
        try:
            await self.coordinator.client.async_delete_event(uid)
        except FamFamApiError as err:
            raise self._write_error("event_delete_failed", err) from err
        finally:
            await self.coordinator.async_refresh()


class FamFamFamilyCalendar(FamFamWritableCalendar):
    """Every family event; creates unassigned (everyone) events."""

    _attr_translation_key = "family"

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.bootstrap.family_id}_calendar_family"

    def _calendar_events(self) -> list[CalendarEvent]:
        return [
            _to_calendar_event(famfam_event)
            for famfam_event in self.coordinator.data.events
        ]


class FamFamMemberCalendar(FamFamWritableCalendar):
    """One member's events; creates events assigned to that member."""

    _attr_translation_key = "member"

    def __init__(self, coordinator: FamFamCoordinator, member: FamFamMember) -> None:
        """Initialise on the member's device."""
        super().__init__(coordinator, member_id=member.id)
        self._member = member
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_calendar_{member.id}"
        )
        # So card authors stop hand-typing hex codes (spec §5.2). The colour
        # is resolved to hex server-side.
        self._attr_extra_state_attributes = {
            "member_id": member.id,
            "member_colour": member.colour,
        }

    def _create_member_ids(self) -> list[str] | None:
        return [self._member.id]

    def _calendar_events(self) -> list[CalendarEvent]:
        member_id = self._member.id
        return [
            _to_calendar_event(famfam_event)
            for famfam_event in self.coordinator.data.events
            # An empty member_ids means the whole family.
            if not famfam_event.member_ids or member_id in famfam_event.member_ids
        ]


class FamFamMealsCalendar(FamFamBaseCalendar):
    """The meal plan as all-day events.

    Read-only for now — the spec's write path is the set_meal_plan service
    of a later release, not calendar event mutation.
    """

    _attr_translation_key = "meals"

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.bootstrap.family_id}_calendar_meals"

    def _calendar_events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for meal in self.coordinator.data.meals:
            if not meal.meal:
                continue
            start = date.fromisoformat(meal.date)
            events.append(
                CalendarEvent(
                    start=start,
                    end=start + timedelta(days=1),
                    summary=meal.meal,
                    uid=meal.date,
                )
            )
        return events
