# FamFam for Home Assistant

**A calendar entity for every family member, and sensors that know who's
home for dinner.** No more single shared calendar with `input_text` filter
helpers and per-person toggle scripts — each member gets their own
`calendar` entity, so filtering is a native calendar-card toggle. And each
member gets a **home-for-dinner** binary sensor driven by FamFam's dinner
check-ins — an automation primitive no other family integration has.

Alongside those: your FamFam lists as to-do entities, the meal plan as its
own calendar, tonight's-dinner and headcount sensors, and a one-tap
"heading to the shops" button. One integration, one token, no per-person
app passwords — a single token covers your whole family.

> **Status:** early development, feature-complete for v1. To-do, calendar,
> sensor, binary-sensor and button platforms, nine services, and six
> ready-made automation blueprints.

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

### Changing the token later

Go to **Settings → Devices & services → FamFam**, open the entry's
**⋮** menu and choose **Reconfigure**. Paste the new token and the
integration reloads with it — your options, entities and automations are
kept. The new token has to belong to the same family.

If the token has already been revoked, Home Assistant offers a
**Re-authenticate** prompt on the FamFam card instead; either route accepts a
fresh token.

## Options

Open the integration's **Configure** dialog to adjust:

| Option | Default | What it does |
|---|---|---|
| Polling interval | 60 s | How often to check famfam.life for changes |
| Default member | Token's member | Who `famfam.set_dinner_checkin` acts on when no member is passed (trip announcements always act as the token's member) |
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
- The meal-plan calendar is read-only — meals are written with the
  `famfam.set_meal` service instead of calendar event mutation.
- Events are served for a bounded window: 7 days back to 28 days forward
  (meals: 14 days ahead). Calendar views beyond that show nothing.
- New family members get their calendar after a reload of the integration.

### Lists

- A `todo` entity per FamFam list, grouped under a **FamFam — {family}** hub
  device, with a `categories` attribute exposing the aisle grouping on
  grocery lists.
- A **remaining-items sensor** per list — the number of unchecked items,
  with `categories` and `oldest_item_added` attributes. Handy for a "12
  items on the grocery list" badge or a stale-list nag.

### Dinner

- A **Home for dinner** binary sensor on each member's device — on when
  that member has checked in as eating tonight, with a `source` attribute
  saying whether the answer was manual or from their usual week.
- **Dinner check-ins complete** — on when everyone has answered for
  tonight, with a `pending` attribute listing who hasn't. Point a nag
  automation at it.
- **Tonight's dinner** — the planned meal as a sensor state, with
  `recipe_id`, `servings`, `prep_time_minutes` and `cook_time_minutes`
  attributes when the meal comes from a recipe.
- **Dinner headcount** — how many people to cook for tonight (members
  eating plus their guests), with `attending`, `not_attending`,
  `no_response` and `guests` attributes. It's a numeric sensor, so
  `numeric_state` triggers work on it.

### Shopping

- **Shopping trip** binary sensor — on while someone is heading to the
  shops, with `member`, `member_colour`, `started_at` and `expires_at`
  attributes.
- **Heading to the shops** button — announces a trip to the whole family,
  exactly like tapping it in the app. Trips are a FamFam Plus feature;
  without Plus the button shows a clear error. The announcement is
  attributed to the member the token belongs to.

### Next events

- A **Next event** sensor for the family and one on each member's device —
  the title of the soonest upcoming event, with a `start` attribute (the
  family one also carries `member` and `member_colour` for single-person
  events).

Notes:

- Items have no separate description or quantity field in FamFam — put
  quantities in the item text (for example "2L milk").
- Base URL only needs changing if you are pointing at a staging server.
- Entity ids are generated from the device and entity names — for example
  `sensor.famfam_smith_tonights_dinner` on the hub, or
  `binary_sensor.alex_home_for_dinner` on a member device. In automations
  and blueprints, pick entities via the device or entity picker rather
  than typing ids.
- New family members get their sensors (like their calendar) after a
  reload of the integration.

## Services

Nine services (actions) for automations, scripts and voice — each one
replaces a pile of helpers and template YAML. All fields have selectors,
so the automation editor's UI mode works throughout. Every service takes
an optional `config_entry_id`; you only need it if more than one FamFam
family is set up.

| Service | What it does |
|---|---|
| `famfam.add_event` | Add a single event, for the whole family or chosen members |
| `famfam.set_dinner_checkin` | Answer a member's dinner check-in — `eating`, `no_meal` or `no_response` (three answers, not a toggle) |
| `famfam.set_meal` | Set the planned meal for a date, from a recipe or free text |
| `famfam.add_meal_ingredients_to_list` | Send planned-meal ingredients to a list, with Shop for Meals deduplication |
| `famfam.add_list_item` | Add an item with an aisle category — which `todo.add_item` can't carry |
| `famfam.start_shopping_trip` | Announce a shopping trip (FamFam Plus) |
| `famfam.end_shopping_trip` | End the current trip; a no-op if none is running |
| `famfam.search_recipes` | Response service: search recipes by text, cuisine, diet, allergen or course |
| `famfam.get_meal_plan` | Response service: the planned meals from today, up to 14 days |

Add an event for one member, by name:

```yaml
action: famfam.add_event
data:
  summary: Swimming lesson
  start: "2026-09-01 15:30:00"
  end: "2026-09-01 16:30:00"
  members:
    - Alex
```

Check a member in as eating tonight (leave `member` off to use the
default member from the options):

```yaml
action: famfam.set_dinner_checkin
data:
  member: Alex
  status: eating
```

The two response services return data into a `response_variable`:

```yaml
- action: famfam.get_meal_plan
  data:
    days: 3
  response_variable: plan
- action: notify.mobile_app_alexs_phone
  data:
    message: >-
      {% for m in plan.meals %}{{ m.date }}: {{ m.meal }}
      {% endfor %}
```

Service notes:

- Deliberate differences from the original spec: the trip services take no
  `member` field (the API always attributes trips to the token's member),
  and `add_event` requires `start`.
- `add_list_item` exists alongside the standard `todo.add_item` because
  the native action can't carry a category. Voice via Assist uses
  `todo.add_item`; automations that know the aisle should use this one.
- Answering the check-in for **another** member needs a token created by
  an organiser; permission errors from FamFam surface as clear error
  messages, never a silent no-op.

## Blueprints

Six ready-made automations. HACS doesn't install an integration's
blueprints, so import them by URL — each badge below opens the importer
with the URL pre-filled. Every FamFam entity is a configurable input
(picked via the entity selector), never a hardcoded id.

| Blueprint | What it does |
|---|---|
| [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbencom-tech%2Ffamfam-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffamfam%2Fdinner_checkin_nudge.yaml) **Dinner check-in nudge** | If check-ins aren't complete at a chosen time, announce it and notify with the names still pending |
| [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbencom-tech%2Ffamfam-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffamfam%2Fannounce_tonights_dinner.yaml) **Announce tonight's dinner** | At a chosen time, announce the planned meal and headcount |
| [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbencom-tech%2Ffamfam-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffamfam%2Fauto_start_shopping_trip.yaml) **Auto-start shopping trip** | Someone arrives at the shops with a non-empty list → announce a trip (Plus) |
| [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbencom-tech%2Ffamfam-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffamfam%2Fshopping_trip_announcement.yaml) **Shopping trip announcement** | A trip starts → announce it, with an "Add an item" notification reply that goes straight onto the list |
| [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbencom-tech%2Ffamfam-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffamfam%2Flist_getting_long.yaml) **List getting long** | A list grows past a threshold → notify |
| [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbencom-tech%2Ffamfam-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffamfam%2Fevent_tomorrow.yaml) **Event tomorrow** | The next event is tomorrow → notify and/or colour a light |
