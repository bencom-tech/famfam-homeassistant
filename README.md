# FamFam for Home Assistant

**A calendar entity for every family member.** No more single shared
calendar with `input_text` filter helpers and per-person toggle scripts —
each member gets their own `calendar` entity, so filtering is a native
calendar-card toggle. Events assigned to the whole family appear on
everyone's calendar, and each member calendar carries `member_id` and
`member_colour` (a resolved hex code) attributes so card authors never
hand-type colours.

Alongside the calendars: your FamFam lists as to-do entities and the meal
plan as its own calendar. One integration, one token, no per-person app
passwords — a single token covers your whole family.

> **Status:** early development. The to-do and calendar platforms are
> available now; dinner check-in sensors, services and blueprints are on
> the way.

## Installation

1. In HACS, open **⋮ → Custom repositories**.
2. Add this repository's URL with category **Integration**.
3. Install **FamFam**, then restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for
   **FamFam**.

## Getting a token

In the FamFam app, go to **Settings → Your Family → Connected services**
(organisers only), create a token and copy it — it is shown once. Paste it
into the config flow. That's the whole setup: install, paste one token, done.

If you revoke a token, allow a minute or so for it to stop working.

## Options

Open the integration's **Configure** dialog to adjust:

| Option | Default | What it does |
|---|---|---|
| Polling interval | 60 s | How often to check famfam.life for changes |
| Default member | Token's member | Who button presses and voice-originated actions act as (used by upcoming platforms) |
| Create a calendar for each member | On | Adds a calendar entity for each family member |
| Lists to show | All | Which FamFam lists appear as to-do lists |

## What you get today

### Calendars

- A calendar entity per family member (on that member's device), showing
  their assigned events plus whole-family events, with `member_id` and
  `member_colour` attributes for card authors.
- A family calendar with every event, and a meal-plan calendar showing each
  planned meal as an all-day event.
- Create, edit and delete events straight from Home Assistant's calendar
  view. Events created on a member's calendar are assigned to that member;
  events created on the family calendar are for everyone.

Calendar notes:

- **Writes are single events only** — repeating events are created and
  edited in the FamFam app. (The Google Calendar integration has the same
  limitation.) A repeating series can still be deleted from Home Assistant
  by choosing "all events".
- Only the person who created an event can change or delete it — the same
  rule as in the app. Other members' events show a clear error.
- The meal-plan calendar is read-only for now; a `set_meal_plan` service is
  coming in a later release.
- Events are served for a bounded window: 7 days back to 28 days forward
  (meals: 14 days ahead). Calendar views beyond that show nothing.
- New family members get their calendar after a reload of the integration.

### Lists

- A `todo` entity per FamFam list, grouped under a **FamFam — {family}** hub
  device, with a `categories` attribute exposing the aisle grouping on
  grocery lists.

Notes:

- Items have no separate description or quantity field in FamFam — put
  quantities in the item text (for example "2L milk").
- Base URL only needs changing if you are pointing at a staging server.
