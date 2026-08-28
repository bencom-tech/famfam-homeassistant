# FamFam for Home Assistant

Bring your family's FamFam lists, calendar, meals and dinner check-ins into
Home Assistant. One integration, one token, no per-person app passwords —
a single token covers your whole family.

> **Status:** early development. The to-do (list) platform is available now;
> per-member calendars, dinner check-in sensors, services and blueprints are
> on the way.

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
| Create a calendar for each member | On | Takes effect when the calendar platform lands |
| Lists to show | All | Which FamFam lists appear as to-do lists |

## What you get today

- A `todo` entity per FamFam list, grouped under a **FamFam — {family}** hub
  device, with a `categories` attribute exposing the aisle grouping on
  grocery lists.
- Devices for each family member, ready for the per-member calendar and
  dinner check-in entities coming in the next releases.

Notes:

- Items have no separate description or quantity field in FamFam — put
  quantities in the item text (for example "2L milk").
- Base URL only needs changing if you are pointing at a staging server.
