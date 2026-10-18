# Home Assistant actions and shortcuts

SimpliFi actions use Home Assistant's existing authenticated connection. They never accept an actor ID, API key or arbitrary UniFi policy body. An active HA administrator can administer the integration. An explicitly granted account can perform only the actions and targets in its current SimpliFi grant; permissions are checked again for each request, including retries.

## Calling actions

Open **Developer tools → Actions** and select a `simplifi` action. Its form documents typed fields. An administrator can run `simplifi.dashboard_data` to find the integration's `entry_id`, group IDs and rule IDs. A scoped account uses `simplifi.access_status`; it receives only its permitted targets.

| Intent | Action | Important fields and behaviour |
| --- | --- | --- |
| Pause a person's internet | `simplifi.pause_internet` | `group_id` plus one timing choice; adds a manual pause and cancels that person's internet allowance. |
| Resume a manual pause | `simplifi.resume_internet` | `group_id`; other scheduled and content restrictions can still block access. |
| Extend a timed pause | `simplifi.extend_pause` | `group_id`, `duration_minutes`; adds minutes to its stored deadline. |
| Allow internet temporarily | `simplifi.allow_internet` | `group_id` plus one timing choice; leaves the manual pause in place and lifts captured managed internet restrictions, preserving content rules and external filters. |
| Return to the internet schedule | `simplifi.end_allowance` | `group_id`; ends the internet allowance. |
| Lift a person's assigned rules together | `simplifi.unblock_group` | `group_id` plus one timing choice; see timing below. |
| End or extend those lifts | `simplifi.end_group_unblock`, `simplifi.extend_group_unblock` | `group_id`; extension also requires `duration_minutes`. |
| Lift one rule | `simplifi.allow_rule`, `simplifi.suspend_rule` | `rule_id`, optional `group_id`, plus one timing choice. Omit the group only when authorised to affect the whole rule. |
| End a rule allowance/suspension | `simplifi.end_rule_allowance`, `simplifi.resume_rule` | The same `rule_id` and optional `group_id`; different allowance kinds remain independent. |
| Extend a rule suspension | `simplifi.extend_rule_suspension` | `rule_id`, optional `group_id`, `duration_minutes`. |
| Enable or disable a saved rule | `simplifi.set_rule_enabled` | `rule_id`, `enabled`; whole-rule permission is required. |
| Pause unknown-device quarantine | `simplifi.suspend_quarantine` | One timing choice; requires scope over every managed network. |
| Resume/extend quarantine | `simplifi.resume_quarantine`, `simplifi.extend_quarantine_suspension` | Extension requires `duration_minutes`; it does not change exclusions or device ownership. |
| Read scoped status | `simplifi.access_status` | No target needed; administrators use `simplifi.dashboard_data`. |
| Read action/sync evidence | `simplifi.activity_history` | Administrator-only; `kind: changes` or `kind: sync`, optional `change_id`, `limit` and cursor. |

Household editing, discovery, DNS, connection, access grants, import/export and recovery actions remain available in the HA action selector and their dedicated dashboard/configuration forms. Scoped editor accounts do not receive connection, DNS, access or recovery administration.

## Timing and command validity

For timed controls choose exactly one of `duration_minutes` (1–10080), a timezone-aware ISO `expires_at`, `next_window_end: true` where supported, or `indefinite: true`. `expires_at` is the **control's end time**. Omitted timing uses that action's default; specify it in a shortcut to avoid ambiguity. Extension actions require a minute duration.

A manual pause takes precedence over an internet allowance. Resume removes that pause; any still-active allowance can then apply for its remaining time. A timed pause can also end at its own deadline. A new pause cancels the internet allowance, and later resuming cannot revive that cancelled allowance.

The default internet allowance captures restrictions active when requested; a later unrelated rule still applies. Default group unblocking lifts currently active assigned rules until each window ends, and always-on rules until ended. An explicit group-unblock duration/time also covers that person's currently assigned enabled rules whose windows start later; subsequently added rules still apply. Quarantine and rule suspension can remain paused indefinitely unless a deadline is supplied. Review the dashboard before choosing an indefinite allowance.

`request_expires_at` is a separate **command delivery deadline**. Use a timezone-aware ISO timestamp no more than five minutes ahead. A new command received at or after that instant fails without changing intent or gateway policies, including when it waited for the engine lock. The bundled card sets a deadline 60 seconds after its latest server observation, independent of the device's wall clock. Refresh a cached/offline screen before making a new request.

External action clients should capture `request_id`, `request_expires_at` and the intended payload together, then keep all of them unchanged for delivery retries. Never regenerate a deadline or request ID merely because a connection failed. A new ID means new intent. `request_expires_at` is optional for compatibility with existing action clients; a client that omits it does not get a command delivery deadline.

`request_id` deduplicates a successful saved request for the same authenticated actor while its change record is retained. An exact retry returns the original result, even after its delivery deadline, without extending or reapplying a control. Reusing that ID with different data fails. Retention is bounded; do not replay old requests after records may have been pruned. An expired delivery deadline still prevents a pruned request from executing again. Revoked, inactive, expired or out-of-scope accounts cannot retrieve a successful retry through the write action.

`expected_revision` optionally rejects a change if saved policy intent has changed since a read. Grant and DNS editing have separate `expected_access_revision` and `expected_dns_revision` fields. These concurrency checks do not replace delivery deadlines or permission checks.

## Authenticated scripts and Companion/Watch shortcuts

[Native script examples](../examples/scripts.yaml) cover pause, resume and temporary internet allowance, with response variables, one-minute delivery deadlines and explicit timing. Replace `REPLACE_ENTRY_ID` and `REPLACE_GROUP_ID` with your real identifiers. Create a native HA script through its UI; paste the definition under one script key into the script's YAML editor. The file also contains the mapping shape for YAML-managed scripts.

Call the named script directly from the authenticated HA app or its approved shortcut facility. Its inner actions preserve the caller and recheck the caller's SimpliFi grant. Making a script does not grant its users additional SimpliFi rights. A script's delivery deadline begins when HA starts that script; it cannot identify an older tap queued before HA received it. Do not configure offline replay or retry loops. Physical Companion/Watch delivery and disconnected behaviour still require testing on the intended client.

Automatic HA triggers do not carry an authenticated user ID; even manually triggering an automation creates a new automation context. These actions reject such calls. Wrapping them in a script, adding an `actor` field, copying a context ID or using `continue_on_error` does not grant authority. Use SimpliFi's native recurring rules for unattended network schedules. There is currently no trusted context-free automation admission path.

For an authorised external agent, use its own existing HA account and an explicit bounded SimpliFi grant. Avoid administrator accounts for routine controls. Leave voice/AI exposure off unless it is deliberately configured and tested. A SimpliFi grant applies to this integration; it cannot restrict that account's independent HA permissions or other UniFi integrations.

## Responses, errors and confirmation

A write normally returns a change record containing `id`, `revision`, authenticated `actor`, `action`, targets, `requested_at`, reason and `outcome`. `pending` means intent was saved for reconciliation; it does not mean the gateway or a child's device has confirmed the effect. Management-disabled changes save intent without enforcing it. DNS checks and access edits use separate outcomes/revisions; read actions return their documented result shape. Request a service response when calling an action, and use a `response_variable` in a native script.

Inspect the same change in Activity or `simplifi.activity_history`. Original failed attempts remain visible; later readback is shown separately for the same revision. A confirmed gateway policy is still distinct from testing traffic on a device. Temporary allowances can outlast their control deadline while Home Assistant is stopped.

HA authentication failures and missing caller identity raise `Unauthorized`. Invalid fields, expired commands, invalid timing, stale revisions, scope violations and retained ownership conflicts fail through HA's service validation/error response. Do not treat a transport timeout as proof of success or failure; refresh evidence and, when retrying, retain the original request envelope. `continue_on_error` can keep a script running after a failure; it cannot turn that failure into a successful policy change.
