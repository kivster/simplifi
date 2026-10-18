# Release status — 0.21.0b1

SimpliFi is a beta custom integration for Home Assistant. Install it as a custom HACS repository or manually; it is not included in HACS's default catalogue.

## Included in this release

- A native Home Assistant integration and bundled Lovelace card with Family, Devices, Rules, Filtering and Activity views.
- People and shared groups, device assignment, internet controls, timed allowances, internet/application/category/domain schedules, selective rule unblocking and coordinated extensions.
- Optional quarantine, controller protection readback, other-policy context, DNS observations, access grants, audit history, configuration export/import and recovery tooling.
- An offline simulator and versioned dashboard resource registration. All integration identifiers, storage and actions use the `simplifi` namespace.
- Continuous/all-day person rule summaries, scoped target names and separate original-action/later-readback evidence in Activity.
- On-demand site device health and bounded controller request accounting, available to HA administrators from the Activity view.
- One bounded fresh inventory retry for conflicting device-network observations, with diagnostic attempt counts and a specific persistent-conflict repair warning. Persistent ambiguity still freezes writes.
- Bounded command delivery, authenticated native script examples and documented action responses, errors, retries and caller context. Unattended context-free automation is not enabled.
- HACS-managed distribution. The old host-wide installer and its credential form and schedule are removed. Legacy installation actions refuse requests and direct administrators to HACS.

## Evidence and limitations

Automated Python tests exercise the simulator, real Home Assistant setup and services, authentication, durable state, reconciliation, resource delivery and updates. JavaScript tests exercise the card's interaction logic. Optional policy-schema tests require a separately acquired official API document.

The [isolated native Core recovery drill](recovery.md#recorded-acceptance) passed 11 cold-process phases for release archives `0.20.1b1` and `0.21.0b1`: update, native backup/restore, retained request retry, compatible rollback and re-upgrade. It preserved saved intent, ownership, identities, permissions, history and customized/unrelated dashboards against an independent durable simulated gateway.

Automated tests and gateway readback are distinct from traffic tests on a device. Outstanding real-environment acceptance includes selective filtering, IPv4/IPv6 and bypass behaviour, quarantine, gateway schedule/DST behaviour, Companion/Watch flows, controller outage recovery and HAOS/Supervisor restoration. Temporary allowances may outlast their deadline while Home Assistant is offline.

The Core drill installs trusted release files directly. A complete HACS installation/update and rollback through HACS remains a separate disposable-instance acceptance check. Follow [migration](migration.md) and [recovery](recovery.md).
