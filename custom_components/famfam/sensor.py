"""Sensor platform for the FamFam integration.

Dinner sensors (tonight's meal and the check-in headcount), a remaining-item
count per list, next-event sensors for the family and each member, and
chores-due counts per chore list and per member.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import (
    FamFamConfigEntry,
    FamFamCoordinator,
    FamFamEvent,
    FamFamItem,
    FamFamList,
    FamFamMember,
    exposed_list_ids,
)
from .entity import FamFamEntity

PARALLEL_UPDATES = 0

# HA rejects sensor states longer than 255 characters; FamFam caps neither
# meal names nor event titles.
MAX_STATE_LENGTH = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamFamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the FamFam sensors."""
    coordinator = entry.runtime_data
    family_id = coordinator.bootstrap.family_id

    entities: list[FamFamEntity] = [
        FamFamTonightsDinnerSensor(coordinator),
        FamFamDinnerHeadcountSensor(coordinator),
        FamFamNextEventSensor(coordinator),
    ]
    entities.extend(
        FamFamMemberNextEventSensor(coordinator, member)
        for member in coordinator.bootstrap.members
    )

    def _chore_list_ids() -> set[str]:
        return {
            list_id
            for list_id in exposed_list_ids(coordinator, entry)
            if coordinator.data.lists[list_id].is_chores
        }

    # Remove stale sensors: members who left, or lists deleted/deselected
    # while HA was down. Live list changes are handled by the listener below,
    # so exposed list ids must count as valid here.
    chore_list_ids = _chore_list_ids()
    valid_unique_ids = (
        {entity.unique_id for entity in entities}
        | {
            f"{family_id}_list_remaining_{list_id}"
            for list_id in exposed_list_ids(coordinator, entry)
        }
        | {f"{family_id}_chores_due_list_{list_id}" for list_id in chore_list_ids}
    )
    if chore_list_ids:
        valid_unique_ids |= {
            f"{family_id}_chores_due_member_{member.id}"
            for member in coordinator.bootstrap.members
        }
    entity_registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if (
            reg_entry.domain == SENSOR_DOMAIN
            and reg_entry.unique_id not in valid_unique_ids
        ):
            entity_registry.async_remove(reg_entry.entity_id)

    async_add_entities(entities)

    # Per-list sensors track the exposed lists live, like the todo platform.
    known: set[str] = set()

    @callback
    def _sync_list_sensors() -> None:
        exposed = exposed_list_ids(coordinator, entry)
        if new_ids := exposed - known:
            async_add_entities(
                FamFamListRemainingSensor(coordinator, list_id)
                for list_id in new_ids
            )
            known.update(new_ids)
        if removed := known - exposed:
            registry = er.async_get(hass)
            for list_id in removed:
                if entity_id := registry.async_get_entity_id(
                    SENSOR_DOMAIN, DOMAIN, f"{family_id}_list_remaining_{list_id}"
                ):
                    registry.async_remove(entity_id)
            known.difference_update(removed)

    _sync_list_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_sync_list_sensors))

    # Chores-due sensors: one per exposed chore list, plus one per member for
    # as long as the family has a chore list exposed at all.
    known_chore_lists: set[str] = set()
    member_chores_added = False

    @callback
    def _sync_chore_sensors() -> None:
        nonlocal member_chores_added
        registry = er.async_get(hass)
        chore_lists = _chore_list_ids()
        if new_ids := chore_lists - known_chore_lists:
            async_add_entities(
                FamFamListChoresDueSensor(coordinator, list_id)
                for list_id in new_ids
            )
            known_chore_lists.update(new_ids)
        if removed := known_chore_lists - chore_lists:
            for list_id in removed:
                if entity_id := registry.async_get_entity_id(
                    SENSOR_DOMAIN, DOMAIN, f"{family_id}_chores_due_list_{list_id}"
                ):
                    registry.async_remove(entity_id)
            known_chore_lists.difference_update(removed)
        if chore_lists and not member_chores_added:
            async_add_entities(
                FamFamMemberChoresDueSensor(coordinator, entry, member)
                for member in coordinator.bootstrap.members
            )
            member_chores_added = True
        elif not chore_lists and member_chores_added:
            for member in coordinator.bootstrap.members:
                if entity_id := registry.async_get_entity_id(
                    SENSOR_DOMAIN,
                    DOMAIN,
                    f"{family_id}_chores_due_member_{member.id}",
                ):
                    registry.async_remove(entity_id)
            member_chores_added = False

    _sync_chore_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_sync_chore_sensors))


def _event_start(
    coordinator: FamFamCoordinator, famfam_event: FamFamEvent
) -> datetime:
    """An event's start as a comparable datetime (all-day = local midnight)."""
    if famfam_event.all_day:
        return datetime.fromisoformat(famfam_event.date).replace(
            tzinfo=coordinator.family_tz
        )
    return datetime.fromisoformat(famfam_event.start)


def _next_event(
    coordinator: FamFamCoordinator, member_id: str | None = None
) -> FamFamEvent | None:
    """The soonest strictly-upcoming event, optionally for one member.

    In-progress events are the calendar entities' job; these sensors answer
    "what's coming up".
    """
    now = dt_util.now()
    upcoming = [
        famfam_event
        for famfam_event in coordinator.data.events
        if _event_start(coordinator, famfam_event) > now
        # An empty member_ids means the whole family.
        and (
            member_id is None
            or not famfam_event.member_ids
            or member_id in famfam_event.member_ids
        )
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda e: _event_start(coordinator, e))


def _import_attributes(famfam_event: FamFamEvent | None) -> dict[str, Any]:
    """Whether the event came from a member's own calendar, and which one."""
    return {
        "imported": bool(famfam_event and famfam_event.imported),
        "imported_from": famfam_event.calendar_name if famfam_event else None,
    }


def _wire_start(famfam_event: FamFamEvent) -> str:
    """The start attribute: a date for all-day events, ISO 8601 otherwise."""
    return famfam_event.date if famfam_event.all_day else famfam_event.start


class FamFamTonightsDinnerSensor(FamFamEntity, SensorEntity):
    """Tonight's planned meal, with recipe details when resolvable."""

    _attr_translation_key = "tonights_dinner"

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.bootstrap.family_id}_tonights_dinner"

    @property
    def native_value(self) -> str | None:
        """The meal name, or unknown when nothing is planned."""
        today = self.coordinator.family_today()
        meal = next(
            (m for m in self.coordinator.data.meals if m.date == today), None
        )
        if meal is None or not meal.meal:
            return None
        return meal.meal[:MAX_STATE_LENGTH]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Recipe details from the coordinator's enrichment cache."""
        today = self.coordinator.family_today()
        meal = next(
            (m for m in self.coordinator.data.meals if m.date == today), None
        )
        recipe_id = meal.recipe_id if meal else None
        recipe = self.coordinator.tonight_recipe
        if recipe is None or recipe.id != recipe_id:
            recipe = None
        return {
            "recipe_id": recipe_id,
            "servings": recipe.servings if recipe else None,
            "prep_time_minutes": recipe.prep_time if recipe else None,
            "cook_time_minutes": recipe.cook_time if recipe else None,
        }


class FamFamDinnerHeadcountSensor(FamFamEntity, SensorEntity):
    """How many people are home for dinner tonight, guests included."""

    _attr_translation_key = "dinner_headcount"
    # measurement so the sensor works as a numeric_state trigger (spec §5.3).
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.bootstrap.family_id}_dinner_headcount"

    def _tonight(self) -> tuple[list[str], list[str], list[str], int]:
        """Names of attending/not attending/no response, and the guest count.

        Members who have left the family since check-in are skipped, so the
        state always equals len(attending) + guests (the app's own total —
        guests are only counted on cells that are actually 'eating').
        """
        day = self.coordinator.data.checkins.get(self.coordinator.family_today())
        responses = day.responses if day else {}
        guest_map = day.guests if day else {}
        attending: list[str] = []
        not_attending: list[str] = []
        no_response: list[str] = []
        guests = 0
        for member in self.coordinator.bootstrap.members:
            response = responses.get(member.id, "no-response")
            if response == "eating":
                attending.append(member.name)
                guests += guest_map.get(member.id, 0)
            elif response == "no-meal":
                not_attending.append(member.name)
            else:
                no_response.append(member.name)
        return attending, not_attending, no_response, guests

    @property
    def native_value(self) -> int:
        """Eating members plus their guests."""
        attending, _, _, guests = self._tonight()
        return len(attending) + guests

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Who answered what, by name (spec §5.3)."""
        attending, not_attending, no_response, guests = self._tonight()
        return {
            "attending": attending,
            "not_attending": not_attending,
            "no_response": no_response,
            "guests": guests,
        }


class FamFamListRemainingSensor(FamFamEntity, SensorEntity):
    """Unchecked items remaining on one list."""

    _attr_translation_key = "list_remaining"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FamFamCoordinator, list_id: str) -> None:
        """Initialise for one list on the family hub device."""
        super().__init__(coordinator)
        self._list_id = list_id
        famfam_list = coordinator.data.lists[list_id]
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_list_remaining_{list_id}"
        )
        self._attr_translation_placeholders = {"list_name": famfam_list.name}

    @property
    def _list(self) -> FamFamList | None:
        return self.coordinator.data.lists.get(self._list_id)

    @property
    def available(self) -> bool:
        """Unavailable when the list disappears server-side."""
        return super().available and self._list is not None

    @property
    def native_value(self) -> int | None:
        """The list doc's unchecked count — no item counting (spec §5.3)."""
        if (famfam_list := self._list) is None:
            return None
        return famfam_list.unchecked_count

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The aisle names and the age marker for stale items."""
        if (famfam_list := self._list) is None:
            return None
        unchecked_added = [
            item.created_at
            for item in famfam_list.items.values()
            if not item.checked and item.created_at
        ]
        return {
            "categories": famfam_list.categories,
            "oldest_item_added": min(unchecked_added, default=None),
        }


class FamFamNextEventSensor(FamFamEntity, SensorEntity):
    """The family's next upcoming event."""

    _attr_translation_key = "next_event"

    def __init__(self, coordinator: FamFamCoordinator) -> None:
        """Initialise on the family hub device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.bootstrap.family_id}_next_event"

    @property
    def native_value(self) -> str | None:
        """The next event's title."""
        if (famfam_event := _next_event(self.coordinator)) is None:
            return None
        return famfam_event.title[:MAX_STATE_LENGTH]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """When it starts and whose it is (single-assignee events only)."""
        famfam_event = _next_event(self.coordinator)
        member: FamFamMember | None = None
        if famfam_event and len(famfam_event.member_ids) == 1:
            member = next(
                (
                    m
                    for m in self.coordinator.bootstrap.members
                    if m.id == famfam_event.member_ids[0]
                ),
                None,
            )
        return {
            "start": _wire_start(famfam_event) if famfam_event else None,
            "member": member.name if member else None,
            "member_colour": member.colour if member else None,
            **_import_attributes(famfam_event),
        }


class FamFamMemberNextEventSensor(FamFamEntity, SensorEntity):
    """One member's next upcoming event (family-wide events included)."""

    _attr_translation_key = "next_event"

    def __init__(self, coordinator: FamFamCoordinator, member: FamFamMember) -> None:
        """Initialise on the member's device."""
        super().__init__(coordinator, member_id=member.id)
        self._member = member
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_next_event_{member.id}"
        )

    @property
    def native_value(self) -> str | None:
        """The next event's title."""
        famfam_event = _next_event(self.coordinator, self._member.id)
        if famfam_event is None:
            return None
        return famfam_event.title[:MAX_STATE_LENGTH]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """When the next event starts."""
        famfam_event = _next_event(self.coordinator, self._member.id)
        return {
            "start": _wire_start(famfam_event) if famfam_event else None,
            **_import_attributes(famfam_event),
        }


def _due_chores(
    coordinator: FamFamCoordinator, famfam_lists: Iterable[FamFamList]
) -> list[tuple[FamFamList, FamFamItem]]:
    """Chores due today or overdue, oldest due date first.

    Any-time and paused chores have no due date and never count; a chore
    already ticked is done (a repeating one comes back with its next date).
    """
    today = coordinator.family_today()
    due = [
        (famfam_list, item)
        for famfam_list in famfam_lists
        for item in famfam_list.items.values()
        if item.is_chore
        and not item.checked
        and not item.paused
        and item.due_date is not None
        and item.due_date <= today
    ]
    due.sort(key=lambda pair: (pair[1].due_date or "", pair[1].text))
    return due


class _FamFamChoresDueSensor(FamFamEntity, SensorEntity):
    """Shared state and attributes for the chores-due sensors."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    # The chore list changes daily; keep it out of the recorder.
    _unrecorded_attributes = frozenset({"chores"})

    def _due(self) -> list[tuple[FamFamList, FamFamItem]]:
        raise NotImplementedError

    @property
    def native_value(self) -> int:
        """How many chores are due today or overdue."""
        return len(self._due())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The due chores themselves, for cards and announcements."""
        due = self._due()
        today = self.coordinator.family_today()
        names = {m.id: m.name for m in self.coordinator.bootstrap.members}
        return {
            "overdue": sum(1 for _, item in due if (item.due_date or "") < today),
            "chores": [
                {
                    "name": item.text,
                    "due": item.due_date,
                    "assignee": names.get(item.assignee_uid)
                    if item.assignee_uid
                    else None,
                    "list": famfam_list.name,
                }
                for famfam_list, item in due
            ],
        }


class FamFamListChoresDueSensor(_FamFamChoresDueSensor):
    """Chores due today or overdue on one chore list, whoever they are for."""

    _attr_translation_key = "chores_due"

    def __init__(self, coordinator: FamFamCoordinator, list_id: str) -> None:
        """Initialise for one chore list on the family hub device."""
        super().__init__(coordinator)
        self._list_id = list_id
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_chores_due_list_{list_id}"
        )
        self._attr_translation_placeholders = {
            "list_name": coordinator.data.lists[list_id].name
        }

    @property
    def available(self) -> bool:
        """Unavailable when the list disappears server-side."""
        return super().available and self._list_id in self.coordinator.data.lists

    def _due(self) -> list[tuple[FamFamList, FamFamItem]]:
        famfam_list = self.coordinator.data.lists.get(self._list_id)
        return _due_chores(self.coordinator, [famfam_list] if famfam_list else [])


class FamFamMemberChoresDueSensor(_FamFamChoresDueSensor):
    """One member's chores due today or overdue, across the exposed chore lists.

    Only chores that are theirs: a chore for anyone counts on its list's
    sensor but on nobody's own.
    """

    _attr_translation_key = "member_chores_due"

    def __init__(
        self,
        coordinator: FamFamCoordinator,
        entry: FamFamConfigEntry,
        member: FamFamMember,
    ) -> None:
        """Initialise on the member's device."""
        super().__init__(coordinator, member_id=member.id)
        self._entry = entry
        self._member = member
        self._attr_unique_id = (
            f"{coordinator.bootstrap.family_id}_chores_due_member_{member.id}"
        )

    def _due(self) -> list[tuple[FamFamList, FamFamItem]]:
        lists = self.coordinator.data.lists
        exposed = [
            lists[list_id]
            for list_id in exposed_list_ids(self.coordinator, self._entry)
            if lists[list_id].is_chores
        ]
        return [
            (famfam_list, item)
            for famfam_list, item in _due_chores(self.coordinator, exposed)
            if item.assignee_uid == self._member.id
        ]
