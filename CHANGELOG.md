# Changelog

All notable changes to the FamFam integration are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

Each release's section is published as its GitHub release notes, which HACS
shows in Home Assistant's update dialog.

## [0.5.0] - 2026-11-08

### Breaking

- **Events tomorrow blueprint:** its input is now a FamFam calendar entity,
  and it reads tomorrow's events with `calendar.get_events`. Automations built
  from the old blueprint need that input set again.

### Fixed

- Calendar: deleting a repeating event from the HA UI no longer always fails.
  Choosing "this and future events" on the first occurrence deletes the whole
  series. Other choices show a hint instead.
- Calendar: editing a series raises a correctly worded error.
- `famfam.add_event`: a date-only start or end now creates an all-day event,
  not one at midnight.
- API client: every response is read and released inside the request, so
  writes give their connection back to HA's pool. Non-JSON or malformed
  responses raise a clear `invalid_response` error.
- Coordinator: the family timezone is looked up without blocking the event
  loop, then cached.
- Setup: permanent 4xx errors and a malformed bootstrap response now fail the
  entry with a clear error, so it stops retrying.

### Changed

- List todo entities and "remaining" sensors take their names from
  translations.
- Options flow drops stale member and list defaults.
- Todo aisle attributes are excluded from the recorder. Diagnostics redact
  names and free text.
- Blueprints: TTS only runs when an engine is set, notification actions get a
  unique id per run, and auto-start passes the config entry.
- README: corrected the default member description. Added removal steps, the
  `item_categories` attribute, and notes on series deletes and the 7-day
  window.

## [0.4.1] - 2026-09-23

### Added

- Reconfigure flow for swapping the API token without removing the
  integration.
- Brand icons for the integrations page.

### Fixed

- After the integration makes a change, data is refetched without the ETag so
  the change appears right away.

### Changed

- Repository moved to `bencom-tech/famfam-homeassistant`.

## [0.4.0] - 2026-08-28

### Added

- Services for adding events, list items and more.
- Automation blueprints.

## [0.3.0] - 2026-08-28

### Added

- Sensor, binary sensor and button platforms.

## [0.2.0] - 2026-08-28

### Added

- Calendar platform.

## [0.1.0] - 2026-08-28

### Added

- First release: config flow, data coordinator and todo lists.

[0.5.0]: https://github.com/bencom-tech/famfam-homeassistant/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/bencom-tech/famfam-homeassistant/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/bencom-tech/famfam-homeassistant/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/bencom-tech/famfam-homeassistant/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/bencom-tech/famfam-homeassistant/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bencom-tech/famfam-homeassistant/releases/tag/v0.1.0
