# Release status — 0.22.0b1

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
- Rule switches use HA's configuration category to stay out of automatic assistant exposure. Existing per-entity exposure choices remain preserved; review older cached choices after upgrading. Deliberate exposure does not bypass authenticated admission.
- HACS-managed distribution. The old host-wide installer and its credential form and schedule are removed. Legacy installation actions refuse requests and direct administrators to HACS.

- Unconfirmed dashboard state now shows the integration's specific sync reason, with a stale-confirmation fallback when no reason is available. Pointer-opened dialogs restore focus to their initiating control after dismissal, including across background refreshes. Long names without spaces wrap within cards and dialogs.

## Person controls and content filters

Each person now has direct Block apps, Block websites, Block categories, Schedules and Content filtering & SafeSearch actions. DNS samples and other UniFi rule diagnostics are collapsed under Advanced diagnostics. DNS answers are no longer presented as a person’s category-control status.

Administrators can edit existing shared UniFi profiles: enabled state, configured content categories, SafeSearch providers, and allowed/blocked domains. A review identifies affected networks and individual devices. The editor preserves scope, schedule and unknown fields, rejects stale reviews, journals uncertain writes before I/O, and verifies controller readback. It uses the matching HA UniFi connection and the local Network v2 API, separate from the official policy API. No profile is changed during installation.

See [content-filter editing](content-filter-editing.md) for shared scope, recovery and compatibility limits.

## Evidence and limitations

Automated Python tests exercise the simulator, real Home Assistant setup and services, authentication, durable state, reconciliation, resource delivery and updates. JavaScript tests exercise the card's interaction logic. Optional policy-schema tests require a separately acquired official API document.

The [native dashboard checks](ui-acceptance.md) cover all five views in WebKit at phone, tablet and desktop viewport sizes, light/dark themes, long names, a rule wizard, dialog dismissal and simulated failure states. These are emulated browser viewports, with physical Companion and Watch acceptance still outstanding.

The [isolated native Core recovery drill](recovery.md#recorded-acceptance) passed 11 cold-process phases for release archives `0.20.1b1` and `0.21.0b1`: update, native backup/restore, retained request retry, compatible rollback and re-upgrade. It preserved saved intent, ownership, identities, permissions, history and customized/unrelated dashboards against an independent durable simulated gateway.

Automated tests and gateway readback are distinct from traffic tests on a device. Outstanding real-environment acceptance includes selective filtering, IPv4/IPv6 and bypass behaviour, quarantine, gateway schedule/DST behaviour, Companion/Watch flows, controller outage recovery and HAOS/Supervisor restoration. Temporary allowances may outlast their deadline while Home Assistant is offline.

The Core drill installs trusted release files directly. A complete HACS installation/update and rollback through HACS remains a separate disposable-instance acceptance check. Follow [migration](migration.md) and [recovery](recovery.md).
