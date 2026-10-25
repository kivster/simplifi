# Gateway compatibility and recovery

SimpliFi uses the local Network Integration API. Application versions such as `10.6.109` are diagnostic information, not an allowlist. An unfamiliar patch, minor or major version is attempted with the same runtime checks. This is forward compatibility by validation, not a guarantee that all future UniFi releases work.

## What is checked

Every normal refresh rereads application information and accessible sites, then validates inventory and the selected scope. Application-version metadata is optional. Required reads validate complete pagination, unique identities, network and firewall-zone relationships, client addresses and network attribution, and the fields used to interpret firewall policies. Extra display fields and metadata are tolerated. Unknown client connection types are not silently omitted from a supposedly complete LAN inventory.

The system-defined External zone is still required. The adapter does not guess that an arbitrary empty zone means the internet. Ambiguous client-network mapping still pauses writes.

Policy changes retain the existing ownership checks, full readback, durable operation journal and uncertain-request handling. Unknown operational fields on an owned policy are not silently removed or ignored: a mismatch pauses automation for inspection. Successful reads are not proof of write compatibility or physical-device enforcement. No test firewall rules are created during compatibility detection.

## When something changes

| Condition | Behaviour |
| --- | --- |
| Unfamiliar application version, usable API | Normal operation; version recorded in diagnostics. |
| Application information unavailable | Version shown as unknown; required reads still determine whether operation can continue. |
| App/category catalogue unavailable | That catalogue is cleared and its editor cannot submit new targets. Independent internet controls can continue. If any saved rule uses that catalogue, the shared policy plan pauses instead of dropping or guessing the rule. |
| Optional DHCP DNS metadata changes | DNS inheritance is unavailable; network control remains independent. |
| Required response missing, malformed or ambiguous | Saved settings and dashboard remain accessible; current control state is unconfirmed and automated policy writes pause. |
| Gateway updating or offline | Existing configuration is retained and coordinator polling retries automatically. |
| API key rejected with HTTP 401 | Home Assistant requests a replacement key for the same controller and site. No reinstall or household reset is needed. |
| API permission denied with HTTP 403 | Show the permission problem; do not assume the key needs replacing. |

Existing gateway policies are not removed merely because a check fails. Gateway-managed schedules continue independently, but changes requiring Home Assistant—including ending a temporary allowance or pause—can be delayed while policy updates are paused. After valid reads return, SimpliFi replans from current time and retained intent, preserving ownership and unresolved-write safeguards. An uncertain write still requires verified readback or explicit recovery; it is never blindly replayed.

## Status and support

The **Gateway compatibility** sensor remains available during a failed refresh:

- `available`: required reads succeeded; this is not a traffic-enforcement claim.
- `limited`: required reads succeeded but optional information is unavailable.
- `paused`: a refresh could not safely complete. The dashboard and diagnostics explain why.
- `authentication_required`: the gateway rejected the API key.
- `checking` / `not_checked`: a fresh result has not been established.
- `simulated`: no live gateway is involved.

Diagnostics include the sanitized application version, whether it is among tested versions, the last check time, optional-feature states and the failure reason. Responses, API keys and household telemetry are not added to compatibility diagnostics. A successful later refresh clears the failure warning automatically. Stale observations never become current just because a version number is familiar.

## Validation

Regression coverage uses the real adapter and policy engine against an independent in-memory API boundary: unfamiliar versions, additive fields, missing required endpoints, malformed identities and policy fields, disappearing catalogues, optional metadata failures, authentication, policy preservation and recovery. Native Home Assistant tests cover loading saved settings during an outage, dashboard access, timer-driven recovery and same-site credential repair. Existing write-recovery and ownership suites remain required.

The baseline official API schema is Network 10.6.106. Live validation against 10.6.109 is read-only, followed by installed-runtime and policy readback. This does not certify future versions or physical-device enforcement.
