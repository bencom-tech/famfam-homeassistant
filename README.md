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

> **Status:** early development. The to-do, calendar, sensor, binary-sensor
> and button platforms are available now; services and blueprints are on
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
| Default member | Token's member | Who voice-originated actions act as (used by the upcoming services; trip announcements always act as the token's member) |
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
