# Contributing

Thanks for helping out. Bug reports, ideas and pull requests are all welcome.

## Questions and ideas

- **Something broken?** Open a [bug report](https://github.com/bencom-tech/famfam-homeassistant/issues/new/choose).
- **Want something new?** Open a feature request.
- **Not sure, or just asking how to do something?** Start a
  [discussion](https://github.com/bencom-tech/famfam-homeassistant/discussions).
- **Security problem?** Follow [SECURITY.md](SECURITY.md) and report it
  privately.

## Pull requests

1. Fork the repo and branch from `main`.
2. Keep each pull request to one change. Open an issue first for anything
   large, so we can agree on the approach before you spend time on it.
3. Follow Home Assistant's
   [integration development guidelines](https://developers.home-assistant.io/docs/creating_component_index).
   User-facing text belongs in `strings.json`, with `translations/en.json`
   kept in step.
4. Lint with [Ruff](https://docs.astral.sh/ruff/) before pushing:
   `ruff check custom_components && ruff format custom_components`.
5. Add an entry for your change under `## [Unreleased]` at the top of
   [CHANGELOG.md](CHANGELOG.md). Create that heading if it isn't there yet.
   Don't bump the version; that happens at release time.
6. Test against a real Home Assistant instance. Install your branch by copying
   `custom_components/famfam` into your config's `custom_components` folder
   and restarting.

The **Hassfest** and **HACS validation** checks must pass before a pull request
can be merged. Pull requests are squash-merged, so the PR title becomes the
commit message. Make it a short description of the change.

## Licence

By contributing you agree that your work is released under the
[MIT License](LICENSE).
