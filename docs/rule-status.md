# Person cards and sync evidence

Person and shared-device cards list managed **Always-on and all-day rules** separately from the day's timed windows. The same summaries are available in the limited access card for the account's authorised rules and groups. They do not add devices, rules or policies to that account's scope.

An always-on rule has no schedule windows. An all-day rule appears in this section when an all-day window falls on the household's current calendar day. A rule with mixed all-day and timed windows can appear here while its timed windows remain in the clock timeline. Clock-change days retain their actual 23-hour or 25-hour boundaries. Rules for other days remain available in the Rules view.

Each row shows the rule name, its application/category/domain targets, whether it belongs to the person or an entire network, and the number of managed devices it covers. Application and category IDs are matched to the cached controller catalogue, including ID zero. Missing or unusable names remain explicit as **Unknown application/category (ID …)**; known names in the same rule are still shown. No catalogue request is made while rendering the card.

| Label | Evidence |
| --- | --- |
| Rule active | The configured restriction is currently active and the saved gateway configuration is confirmed. This is not a traffic test. |
| Some devices restricted | The rule covers only the displayed subset of the person's managed devices. |
| Temporarily lifted | A matching temporary exception is active and its configuration is confirmed. |
| Rule/Allowance unconfirmed | Saved intent cannot currently be confirmed by fresh gateway readback. |
| Saved · management off | The rule is saved while gateway management is disabled. |
| Disabled | The managed rule is disabled. |
| No managed devices | No currently in-scope devices are covered. |
| Archived person | The person is archived; the row does not claim that their person rules are enforced. |

Stale coverage is labelled last known. A network rule opens **Network options** without silently narrowing it to a person. A person rule opens options with that person's scope. Read-only accounts see status without controls. Every action is authorised again by the backend.

## Activity after a failed attempt

Activity preserves each saved action's original result. It also shows the latest retained sync for that exact saved revision, after the action was requested. When a later run confirms that revision without unresolved operations, a failed action row reads **Original attempt failed**, followed by **Later settings readback confirmed** and its timestamp.

An unrelated revision, an interrupted/running attempt, incomplete confirmation metadata or a newer failed sync cannot supply that confirmation. If history has expired, the view says no retained result is available. DNS and access-grant changes do not borrow policy-sync results.

The later readback describes the settings in effect at that time. It does not establish that an earlier pause or allowance ran before its deadline, or that client traffic was blocked. Earlier failed attempts stay available through **View sync results**. The compact rows and history pages use cached records; they do not ask the gateway to sync or rewrite saved outcomes.
