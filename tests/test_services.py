"""The skip_chore and set_away actions, and the chore-list guard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.famfam.const import CONF_DEFAULT_MEMBER, DOMAIN

from .conftest import calls
from .const import ALEX, API, CHORE_LIST, GROCERY_LIST, SAM

EntityId = Callable[[str, str], str | None]


async def _call(hass: HomeAssistant, service: str, data: dict[str, Any]) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize("chore", ["Bins", "bins", "ch1"])
async def test_skip_chore_by_name_or_uid(
    hass: HomeAssistant, entity_id: EntityId, mock_api: AiohttpClientMocker, chore: str
) -> None:
    """A chore can be named the way a person would say it."""
    mock_api.post(f"{API}/lists/{CHORE_LIST}/items/ch1/skip", json={"id": "ch1"})
    await _call(
        hass,
        "skip_chore",
        {"list_entity_id": entity_id("todo", CHORE_LIST), "chore": chore},
    )
    assert len(calls(mock_api, "POST", f"/lists/{CHORE_LIST}/items/ch1/skip")) == 1


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("list_id", "chore", "key"),
    [
        (CHORE_LIST, "Ironing", "chore_not_found"),
        # Done already, so there is nothing left to skip by that name.
        (CHORE_LIST, "Vacuum", "chore_not_found"),
        # A grocery item, addressed by uid.
        (GROCERY_LIST, "g1", "not_a_chore"),
    ],
)
async def test_skip_chore_rejects_what_it_cannot_skip(
    hass: HomeAssistant,
    entity_id: EntityId,
    mock_api: AiohttpClientMocker,
    list_id: str,
    chore: str,
    key: str,
) -> None:
    """Nothing is sent for a chore that can't be resolved."""
    mock_api.mock_calls.clear()
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            "skip_chore",
            {"list_entity_id": entity_id("todo", list_id), "chore": chore},
        )
    assert err.value.translation_key == key
    assert mock_api.mock_calls == []


async def test_skip_chore_with_two_chores_of_the_same_name(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    state_payload: dict[str, Any],
    entity_id: EntityId,
) -> None:
    """An ambiguous name is refused, not guessed."""
    chores = next(lst for lst in state_payload["lists"] if lst["id"] == CHORE_LIST)
    chores["items"][1]["text"] = "Bins"
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            "skip_chore",
            {"list_entity_id": entity_id("todo", CHORE_LIST), "chore": "Bins"},
        )
    assert err.value.translation_key == "chore_ambiguous"


@pytest.mark.usefixtures("init_integration")
async def test_set_away_with_a_back_on_date(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """A member is named and the date goes through as a date key."""
    mock_api.put(f"{API}/members/{SAM}/away", json={"memberId": SAM})
    await _call(
        hass, "set_away", {"member": "Sam", "away": True, "back_on": "2026-12-05"}
    )
    (put,) = calls(mock_api, "PUT", f"/members/{SAM}/away")
    assert put[2] == {"away": True, "backOn": "2026-12-05"}


@pytest.mark.usefixtures("init_integration")
async def test_set_away_off_uses_the_default_member_and_drops_the_date(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> None:
    """Marking someone back needs no date, and no member when one is set."""
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_DEFAULT_MEMBER: ALEX}
    )
    await hass.async_block_till_done()
    mock_api.put(f"{API}/members/{ALEX}/away", json={"memberId": ALEX})
    await _call(hass, "set_away", {"away": False, "back_on": "2026-12-05"})
    (put,) = calls(mock_api, "PUT", f"/members/{ALEX}/away")
    assert put[2] == {"away": False}


@pytest.mark.usefixtures("init_integration")
async def test_set_away_validates_before_sending(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """A back-on date of today would not be away at all."""
    mock_api.mock_calls.clear()
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass, "set_away", {"member": "Sam", "away": True, "back_on": "2026-11-22"}
        )
    assert err.value.translation_key == "back_on_not_future"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "set_away", {"away": True})
    assert err.value.translation_key == "member_required"
    assert mock_api.mock_calls == []


@pytest.mark.usefixtures("init_integration")
async def test_set_away_for_someone_else_needs_an_organiser(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """The refusal is worded for away, not for dinner check-ins."""
    mock_api.put(
        f"{API}/members/{SAM}/away",
        status=403,
        json={"error": {"code": "organiser_only", "message": "Organisers only."}},
    )
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "set_away", {"member": "Sam", "away": True})
    assert err.value.translation_key == "away_organiser_only"


async def test_new_actions_need_the_server_to_support_them(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    bootstrap_payload: dict[str, Any],
    entity_id: EntityId,
) -> None:
    """Against an older server the actions explain themselves, not 404."""
    bootstrap_payload["capabilities"] = ["calendar", "lists", "meals", "checkins"]
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_api.mock_calls.clear()
    for service, data in (
        (
            "skip_chore",
            {"list_entity_id": entity_id("todo", CHORE_LIST), "chore": "Bins"},
        ),
        ("set_away", {"member": "Sam", "away": True}),
    ):
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, service, data)
        assert err.value.translation_key == "server_feature_unavailable"
    assert mock_api.mock_calls == []


@pytest.mark.usefixtures("init_integration")
async def test_meal_ingredients_are_not_sent_to_a_chore_list(
    hass: HomeAssistant, entity_id: EntityId, mock_api: AiohttpClientMocker
) -> None:
    """Each ingredient would otherwise become a chore."""
    mock_api.mock_calls.clear()
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            "add_meal_ingredients_to_list",
            {
                "date_from": "2026-11-23",
                "list_entity_id": entity_id("todo", CHORE_LIST),
            },
        )
    assert err.value.translation_key == "list_is_chores"
    assert mock_api.mock_calls == []
