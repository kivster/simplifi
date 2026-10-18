# Changelog

## 0.21.0b1 — 2026-10-18

- Add optional command delivery deadlines, separate from temporary-control end times. Expired new requests and validity beyond five minutes are rejected under the write lock. Exact retained retries return the original change without extending or reapplying controls; permissions are checked again.
- Bound card mutations to one minute after the latest server observation, including scoped cards, without depending on the device wall clock. Old cached screens need a fresh read.
- Publish typed action and response/error guidance, real native script examples and explicit authenticated-context requirements. Automatic triggers remain unauthorised; no account or grant permissions are widened.

## 0.20.1b1 — 2026-10-18

- Retry inconsistent device-network observations once with a complete fresh read, a one-second settling delay and a 30-second retry budget. Keep current-client reads adjacent to reduce avoidable skew.
- Persistent disagreement, missing corroboration after a conflict, malformed data and incomplete reads still freeze policy writes and retain saved settings, assignments and ownership evidence.
- Add identifier-free discovery attempt diagnostics and a specific repair warning for persistent device-network conflicts. Policy drift and uncertain writes retain their existing recovery safeguards.

## 0.20.0b1 — 2026-10-18

- Show always-on and today's all-day restrictions on person/shared-device cards and scoped access cards, with named targets, explicit unknown IDs, device coverage and confirmed/lifted/stale states. Keep them out of the timed clock rows.
- Keep person and network option scopes explicit; read-only accounts receive status without controls.
- Show cached later readback for each saved revision on Activity and change-history rows while preserving original failed attempts. Unrelated revisions, newer failed runs and incomplete metadata cannot supply confirmation.
- No policy planning, stored outcomes, ownership receipts or household dashboard layout changes.

## 0.19.0b2 — 2026-10-18

- Identify gateways by an exact, unique MAC match in the existing site-matched HA UniFi device cache when the official API omits the gateway feature and reports a WAN address. This does not issue another controller request or infer roles from product names.
- Label the cached role source, partial samples and dated timezone-aware sample times explicitly. Separate network-reference requests in the traffic meter.

## 0.19.0b1 — 2026-10-18

- Add an administrator-only Gateway load dialog with on-demand device CPU, memory, load averages, uptime and timestamped sample freshness.
- Count this integration's controller HTTP exchanges, retries, failures, rate limits, latency and concurrency over a bounded five-minute window, with fixed endpoint labels and no credentials or household identifiers.
- Reuse the existing HA UniFi connection and HTTP pool for filtering and current-network reads; account for native reauthentication without patching the shared client.
- Keep routine dashboard and diagnostics reads cached. Device-statistics reads are explicit, bounded to 64 devices and four simultaneous requests, and limited to once per minute.

## 0.18.0b3 — 2026-10-18

- Accept reordered weekdays when confirming weekly UniFi schedules, including overnight windows crossing Sunday.
- Preserve existing raw ownership receipts while comparing schedule semantics; changed devices, zones, times and other fields still freeze writes.
- Apply the same comparison to pending writes, recovery evidence, ownership readback and dashboard confirmation.

A saved create identity is recovered by readback without recreating the policy. No household data migration is required.

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
