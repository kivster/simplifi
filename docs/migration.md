# Migrating an existing installation

This is the in-place migration plan for the beta release. Live household migration requires a verified backup and has not yet been accepted with this package.

1. Finish or recover any active installation in the previous updater. Confirm that its scheduled updates and any external deployment job will no longer overwrite `custom_components/family_network` or reinstall the previous dashboard card.
2. Take and verify a Home Assistant backup, including integration configuration, stored household state, policy ownership journal and history. Retain the previous integration files and dashboard resource URL for rollback.
3. Install the reviewed SimpliFi release over the existing integration directory through HACS or the documented manual installation path. Do not delete and recreate the integration entry.
4. Restart Home Assistant once. Confirm that the same entry, people, devices, rules, grants, history and policy ownership remain present.
5. Inspect the Lovelace resource URL and reload the frontend. Storage resources for the existing card are migrated automatically. YAML resources require the change documented in [dashboard setup](dashboard.md).
6. Check fresh gateway readback, policy counts and the activity history before testing a single explicitly selected device.

The integration domain, service names, storage keys, custom element name and entity unique IDs remain `family_network`-based. Existing custom entry and dashboard titles are retained; rename them to SimpliFi through Home Assistant if desired. Existing gateway policy names are retained to avoid writes caused solely by rebranding.

The previous updater's GitHub credential is removed from the config entry using Home Assistant's API. Its recovery record is preserved but no old installation or schedule is resumed. An unresolved or unreadable record produces an Activity-view notice. Resolve any previous installer state before proceeding with another update.

For rollback, restore the previous integration files and matching dashboard resource, then restart and verify the stored state against the backup. The obsolete GitHub credential would need to be entered again if you deliberately restore the old updater. Restore stored household data only from a matching verified backup; do not manually edit Home Assistant's `.storage` files.
