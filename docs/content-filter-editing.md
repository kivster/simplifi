# Content filtering and everyday controls

On a person’s card, **Block apps**, **Block websites**, **Block categories** and **Schedules** open the rule wizard with that person already selected. Review the target and timing before saving. Application categories describe UniFi traffic identification; content categories such as adult content belong to UniFi content-filter profiles.

**Content filtering & SafeSearch** shows enabled profiles that match the person’s known devices. To see disabled profiles as well, open **Filtering**. A disabled profile does not disable another profile covering the same network.

## Edit an existing UniFi profile

Expand a profile in Filtering and choose **Edit content filter**. Administrators can change its enabled state, blocked content categories, Google/Bing/YouTube SafeSearch, and allowed/blocked domain lists. Category choices come from categories already observed on this controller, preserving existing entries. Creating profiles, changing their device/network assignments and changing their own schedules remain in UniFi.

Review shows the current and proposed values plus affected networks and individually assigned devices. A profile shared with other people affects those people too, including devices outside SimpliFi. A per-person internet allowance does not bypass these filters.

Save uses the existing matching Home Assistant UniFi connection and the local Network v2 `PUT /content-filtering/{id}` API. The entire profile is re-read before saving; if it has changed since review, reopen the editor. Scope, schedule and unknown properties are retained. The adapter checks the complete response shape and reads back the saved profile. This local API is compatibility-sensitive and separate from the official Integration API. Controller permissions may deny edits even when readback works.

Reviews are administrator-bound, expire after five minutes and cannot be replayed after a write. A private HA storage journal records before/after editable values and outcome before the request is sent. A timeout or differing readback is reported as unconfirmed; another write is blocked until a new read resolves the retained outcome. Inspect the profile in UniFi if drift prevents resolution. Do not blindly repeat a save. To reverse a confirmed edit, reopen the profile and review the previous values as a new edit.

Installation itself never changes a profile. Automated tests cover edits and failure handling against an isolated controller double; a production profile mutation and physical-device enforcement check are separate acceptance steps.

## Advanced diagnostics

DNS samples live under **Advanced diagnostics**. “Run HA DNS samples” queries from the Home Assistant host. A person context chooses a resolver; it does not place the query on that person’s device or network. DNS resolving does not prove application access; DNS blocking does not prove every device or bypass path is covered. Use physical-device tests when confirming enforcement.
