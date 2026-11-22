"""Payloads the mocked FamFam API serves.

NOW is midday on Sunday 22 November 2026 in the family's timezone, so
"today" is 2026-11-22 wherever the tests run.
"""

from __future__ import annotations

from typing import Any

BASE_URL = "https://famfam.life"
API = f"{BASE_URL}/api/v1/ha"
TOKEN = "test-token"
FAMILY_ID = "fam1"
NOW = "2026-11-22T02:00:00+00:00"
TODAY = "2026-11-22"

ALEX = "u1"
SAM = "u2"
GROCERY_LIST = "l1"
CHORE_LIST = "c1"

BOOTSTRAP: dict[str, Any] = {
    "family": {
        "id": FAMILY_ID,
        "name": "Smith",
        "region": "AU",
        "timezone": "Australia/Brisbane",
        "tier": "plus",
    },
    "members": [
        {
            "id": ALEX,
            "name": "Alex",
            "initials": "A",
            "colour": "#46583c",
            "avatarIcon": None,
            "role": "organiser",
        },
        {
            "id": SAM,
            "name": "Sam",
            "initials": "S",
            "colour": "#c5836f",
            "avatarIcon": None,
            "role": "member",
        },
    ],
    "lists": [
        {
            "id": GROCERY_LIST,
            "name": "Groceries",
            "isGrocery": True,
            "sharing": "family",
        },
        {
            "id": CHORE_LIST,
            "name": "Chores",
            "isGrocery": False,
            "sharing": "family",
            "kind": "chores",
        },
    ],
    "capabilities": [
        "calendar",
        "lists",
        "meals",
        "checkins",
        "chores",
        "away",
        "trips",
    ],
    "stateVersion": 7,
}


def _item(
    item_id: str, text: str, checked: bool = False, **extra: Any
) -> dict[str, Any]:
    return {
        "id": item_id,
        "text": text,
        "checked": checked,
        "category": None,
        "addedBy": ALEX,
        "checkedBy": ALEX if checked else None,
        "createdAt": "2026-11-01T00:00:00.000Z",
        "updatedAt": "2026-11-01T00:00:00.000Z",
        **extra,
    }


STATE: dict[str, Any] = {
    "stateVersion": 7,
    "generatedAt": NOW.replace("+00:00", ".000Z"),
    "timezone": "Australia/Brisbane",
    "lists": [
        {
            "id": GROCERY_LIST,
            "name": "Groceries",
            "isGrocery": True,
            "sharing": "family",
            "sortMode": "aisles",
            "uncheckedCount": 1,
            "categories": ["Dairy"],
            "items": [_item("g1", "Milk", category="Dairy")],
        },
        {
            "id": CHORE_LIST,
            "name": "Chores",
            "isGrocery": False,
            "sharing": "family",
            "sortMode": "flat",
            "uncheckedCount": 5,
            "categories": None,
            "kind": "chores",
            "items": [
                # Due today, Alex's, repeating.
                _item("ch1", "Bins", dueDate=TODAY, assigneeUid=ALEX, repeats=True),
                # Overdue, Sam's.
                _item(
                    "ch2",
                    "Lawn",
                    dueDate="2026-11-20",
                    assigneeUid=SAM,
                    repeats=True,
                    note="Front only",
                ),
                # Any time, for anyone, one-off.
                _item(
                    "ch3", "Tidy garage", dueDate=None, assigneeUid=None, repeats=False
                ),
                # Paused: no due date either.
                _item(
                    "ch4",
                    "Wash car",
                    dueDate=None,
                    assigneeUid=ALEX,
                    repeats=True,
                    paused=True,
                ),
                # Not due yet.
                _item(
                    "ch5",
                    "Dishes",
                    dueDate="2026-11-25",
                    assigneeUid=ALEX,
                    repeats=True,
                ),
                # A one-off already done today.
                _item(
                    "ch6",
                    "Vacuum",
                    checked=True,
                    dueDate=TODAY,
                    assigneeUid=ALEX,
                    repeats=False,
                ),
            ],
        },
    ],
    "events": [
        {
            "id": "e1",
            "masterId": "e1",
            "title": "Swimming",
            "date": "2026-11-23",
            "allDay": False,
            "start": "2026-11-23T09:00:00+10:00",
            "end": "2026-11-23T10:00:00+10:00",
            "memberIds": [ALEX],
            "createdBy": ALEX,
            "location": None,
            "notes": None,
            "repeat": "never",
        },
        {
            "id": "imp_1",
            "masterId": "imp_1",
            "title": "Dentist",
            "date": "2026-11-24",
            "allDay": False,
            "start": "2026-11-24T14:00:00+10:00",
            "end": "2026-11-24T15:00:00+10:00",
            "memberIds": [ALEX],
            "createdBy": ALEX,
            "location": None,
            "notes": None,
            "repeat": "never",
            "imported": True,
            "calendarName": "Work",
        },
    ],
    "meals": [],
    "checkins": [],
    "trip": None,
    "away": [{"memberId": SAM, "backOn": "2026-11-25"}],
}

# What a server from before chores, imports and away serves: the same family
# with none of the newer keys anywhere.
LEGACY_BOOTSTRAP: dict[str, Any] = {
    **BOOTSTRAP,
    "lists": [
        {k: v for k, v in lst.items() if k != "kind"} for lst in BOOTSTRAP["lists"]
    ],
    "capabilities": ["calendar", "lists", "meals", "checkins", "trips"],
}
_CHORE_KEYS = {"dueDate", "assigneeUid", "repeats", "paused", "note"}
LEGACY_STATE: dict[str, Any] = {
    **{k: v for k, v in STATE.items() if k != "away"},
    "lists": [
        {
            **{k: v for k, v in lst.items() if k != "kind"},
            "items": [
                {k: v for k, v in item.items() if k not in _CHORE_KEYS}
                for item in lst["items"]
            ],
        }
        for lst in STATE["lists"]
    ],
    "events": [
        {k: v for k, v in event.items() if k not in {"imported", "calendarName"}}
        for event in STATE["events"]
    ],
}
