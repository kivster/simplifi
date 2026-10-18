# Release status — 0.19.0b2

SimpliFi is a beta custom integration for Home Assistant. Install it as a custom HACS repository or manually; it is not included in HACS's default catalogue.

## Included in this release

- A native Home Assistant integration and bundled Lovelace card with Family, Devices, Rules, Filtering and Activity views.
- People and shared groups, device assignment, internet controls, timed allowances, internet/application/category/domain schedules, selective rule unblocking and coordinated extensions.
- Optional quarantine, controller protection readback, other-policy context, DNS observations, access grants, audit history, configuration export/import and recovery tooling.
- An offline simulator and versioned dashboard resource registration. All integration identifiers, storage and actions use the `simplifi` namespace.
- On-demand site device health and bounded controller request accounting, available to HA administrators from the Activity view.
- HACS-managed distribution. The old host-wide installer and its credential form and schedule are removed. Legacy installation actions refuse requests and direct administrators to HACS.

## Evidence and limitations

Automated Python tests exercise the simulator, real Home Assistant setup and services, authentication, durable state, reconciliation, resource delivery and updates. JavaScript tests exercise the card's interaction logic. Optional policy-schema tests require a separately acquired official API document.

Automated tests and gateway readback are distinct from traffic tests on a device. Outstanding real-environment acceptance includes selective filtering, IPv4/IPv6 and bypass behaviour, quarantine, gateway schedule/DST behaviour, Companion/Watch flows, outage recovery and full restore. Temporary allowances may outlast their deadline while Home Assistant is offline.

A complete HACS installation/update and rollback should be checked on a disposable restored instance before replacing an existing live installation. Follow [migration](migration.md).
