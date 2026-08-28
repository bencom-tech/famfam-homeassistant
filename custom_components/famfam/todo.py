"""Todo platform for the FamFam integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.todo import (
    DOMAIN as TODO_DOMAIN,
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import FamFamApiError
from .const import CONF_LISTS, DOMAIN
from .coordinator import FamFamConfigEntry, FamFamCoordinator, FamFamList
from .entity import FamFamEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamFamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FamFam todo entities from the exposed lists."""
    coordinator = entry.runtime_data
    family_id = coordinator.bootstrap.family_id
    known: set[str] = set()

    def _exposed_ids() -> set[str]:
        ids = set(coordinator.data.lists)
        # Absent key means all lists — new FamFam lists appear automatically.
        if CONF_LISTS in entry.options:
            ids &= set(entry.options[CONF_LISTS])
        return ids

    @callback
    def _sync_entities() -> None:
        exposed = _exposed_ids()
        if new_ids := exposed - known:
            async_add_entities(
                FamFamTodoListEntity(coordinator, list_id) for list_id in new_ids
            )
            known.update(new_ids)
        if removed := known - exposed:
            entity_registry = er.async_get(hass)
            for list_id in removed:
                if entity_id := entity_registry.async_get_entity_id(
                    TODO_DOMAIN, DOMAIN, f"{family_id}_{list_id}"
                ):
                    entity_registry.async_remove(entity_id)
            known.difference_update(removed)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class FamFamTodoListEntity(FamFamEntity, TodoListEntity):
    """A FamFam list as a todo entity."""

    # No SET_DESCRIPTION_ON_ITEM: FamFam items have no description field, and
    # omitting the feature makes the todo service layer reject the field.
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: FamFamCoordinator, list_id: str) -> None:
        """Initialise for one list."""
        super().__init__(coordinator)
        self._list_id = list_id
        famfam_list = coordinator.data.lists[list_id]
        self._attr_unique_id = f"{coordinator.bootstrap.family_id}_{list_id}"
        self._attr_name = famfam_list.name
        self._attr_translation_key = (
            "grocery_list" if famfam_list.is_grocery else "list"
        )

    @property
    def _list(self) -> FamFamList | None:
        return self.coordinator.data.lists.get(self._list_id)

    @property
    def available(self) -> bool:
        """Unavailable when the list disappears server-side."""
        return super().available and self._list is not None

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Map the list's items, server order preserved."""
        if (famfam_list := self._list) is None:
            return None
        return [
            TodoItem(
                uid=item.id,
                summary=item.text,
                status=TodoItemStatus.COMPLETED
                if item.checked
                else TodoItemStatus.NEEDS_ACTION,
            )
            for item in famfam_list.items.values()
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the aisle grouping for card authors (spec §5.1)."""
        if (famfam_list := self._list) is None:
            return None
        return {
            # The family's aisle names (grocery lists only, else None).
            "categories": famfam_list.categories,
            # uid → aisle, so cards can group todo_items without extra lookups.
            "item_categories": {
                item.id: item.category
                for item in famfam_list.items.values()
                if item.category
            },
        }

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item to the list."""
        try:
            await self.coordinator.client.async_create_item(
                self._list_id, item.summary or ""
            )
        except FamFamApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="item_create_failed",
                translation_placeholders={"code": err.code},
            ) from err
        finally:
            await self.coordinator.async_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """PATCH only the fields that actually changed (data-loss guard)."""
        if TYPE_CHECKING:
            assert item.uid
        famfam_list = self._list
        current = famfam_list.items.get(item.uid) if famfam_list else None
        if current is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="item_not_found"
            )
        changes: dict[str, Any] = {}
        if item.summary is not None and item.summary != current.text:
            changes["text"] = item.summary
        if item.status is not None:
            checked = item.status == TodoItemStatus.COMPLETED
            if checked != current.checked:
                changes["checked"] = checked
        if not changes:
            return
        try:
            await self.coordinator.client.async_update_item(
                self._list_id, item.uid, changes
            )
        except FamFamApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="item_update_failed",
                translation_placeholders={"code": err.code},
            ) from err
        finally:
            await self.coordinator.async_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items from the list."""
        try:
            for uid in uids:
                await self.coordinator.client.async_delete_item(self._list_id, uid)
        except FamFamApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="item_delete_failed",
                translation_placeholders={"code": err.code},
            ) from err
        finally:
            await self.coordinator.async_refresh()
