# Changelog

## 0.18.0b2 — 2026-10-18

- Use `simplifi` consistently for the integration folder and domain, service actions, storage keys, export format, dashboard URLs and bundled card.
- Rename component classes, tests, tools and packaging paths to match SimpliFi.
- Name newly created gateway policies with the SimpliFi prefix.

Replacing a prototype or the initial beta requires a fresh setup. Follow the migration guide to clean up owned policies and retain a verified backup first.

## 0.18.0b1 — 2026-10-18

Initial standalone beta release of SimpliFi.

- Native Home Assistant integration for local UniFi family internet controls, with an offline simulator.
- Bundled Family, Devices, Rules, Filtering and Activity dashboard views.
- People and shared device groups, assignments, schedules, timed allowances, selective unblocking, coordinated extensions and optional quarantine.
- Protection and other-policy readback, DNS observations, scoped access grants, activity history and recovery tools.
- HACS distribution and a versioned dashboard resource served directly by the integration.

The former host-wide installer is removed. Manage integration updates through HACS and follow the migration guide. This beta retains the real-environment acceptance limitations described in `docs/release-status.md`.
