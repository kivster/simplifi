# Replacing an earlier installation

SimpliFi uses the `simplifi` integration domain, storage namespace and export format. This beta does not automatically migrate entries or policy ownership from a differently named prototype or the initial standalone beta. Installing it alongside an active predecessor can leave two independent policy managers.

1. Take and verify a Home Assistant backup. Retain the previous integration files and a household configuration export privately for recovery.
2. Disable management in the previous integration. Review its policy ownership and use its own cleanup action to remove only the gateway policies it owns. Confirm that lifting those restrictions is acceptable and verify fresh controller readback.
3. Remove the previous integration entry, its dedicated dashboard and its card resource through Home Assistant. Stop any previous updater or external deployment that could reinstall it, then remove its integration files. Keep unrelated UniFi integrations and policies.
4. Add `kivster/simplifi` as an Integration custom repository in HACS, enable beta releases and download SimpliFi. Restart Home Assistant once when prompted.
5. Add SimpliFi through **Settings → Devices & services**. Start in the simulator or observation mode, select the managed scope and recreate the household configuration. Exports carrying a different integration format are not directly accepted.
6. Create the dashboard following [dashboard setup](dashboard.md). Assign devices, review the scope and enable management only when ready. Verify fresh gateway readback and test one explicitly selected device.

For later updates within the `simplifi` domain, use HACS and follow its restart prompt. Existing SimpliFi entries and stored household state remain in place.

For rollback, use the matching verified backup and previous files. Avoid restoring an old policy ownership journal over a gateway whose policies have changed. Do not manually edit Home Assistant's `.storage` files. Resolve outstanding installer or recovery attempts before switching policy managers.
