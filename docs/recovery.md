# Backups and release rollback

A portable SimpliFi export and a native Home Assistant backup serve different purposes:

| Recovery material | Preserves |
| --- | --- |
| SimpliFi configuration export | Household groups, rules, assignments and supported settings. It excludes controller credentials, HA users, access grants, temporary controls and policy ownership. Import requires a reviewed scope mapping and creates its own ownership evidence. |
| Native Home Assistant backup | The selected HA configuration, including integration connection data, native users, registries, Lovelace dashboards, SimpliFi intent, ownership journal and history. Treat it as sensitive. Recorder database and other system components depend on the backup options. |

The UniFi controller is independent of either backup. Restoring HA does not restore the controller's policies to the same point in time. An old ownership journal must not be treated as proof of present gateway state. If readback disagrees or an operation is uncertain, retain the evidence and use the integration's recovery preview before resolving it. Do not edit `.storage` or adopt policies by name.

## Updating and rolling back an installed integration

1. Take and verify a native HA backup before updating. Keep the current SimpliFi version, a private configuration export and a record of any pending recovery issue.
2. Use HACS to select the release and follow its restart prompt. HACS installs integration files; SimpliFi does not update other components or restart HA itself.
3. Check the installed version, integration loading, fresh gateway readback, person/device assignments, access grants and existing dashboard edits. Verify a selected device separately before treating readback as traffic proof.
4. If rollback is needed, choose the previously verified compatible release in HACS and restart. Check the same evidence again before issuing controls. Earlier releases retain their earlier action semantics.
5. Restore native HA backup data only through Home Assistant's supported restore flow, after reviewing whether the gateway has changed since that backup. A file rollback and a configuration restore are distinct operations. Keep the existing evidence when uncertain.

This procedure does not assert that every older release can read newer stored data. Unsupported schemas must remain preserved for recovery. See [migration](migration.md) when replacing an integration with a different identity.

## Repeatable isolated Core drill

`tools/simplifi/recovery_drill.py` creates a new, private temporary configuration and uses fictional devices only. Each phase boots a fresh native HA Core process with real disk stores. The simulated controller is durable outside the HA backup, so restoring HA cannot reset it to make ownership comparisons pass.

The drill exercises:

- Cold persistence, an update from a verified previous release, rollback and re-upgrade.
- Native HA Core backup creation, a visible configuration change after backup, native restore and a cold start from the restored archive.
- A manual pause alongside an internet allowance, plus a retained exact request retry after restore.
- Saved assignments, rules, HA users, access grants, entry/entity identities, ownership IDs, journal receipts and retained history.
- A customized generated dashboard, a separate unrelated dashboard and an unrelated resource. Only the SimpliFi resource's version URL may change.
- No duplicate simulated policy creation during cold startup, update, restore or rollback.

Use Python 3.14 on a disposable Linux development runner and trusted release archives. The Ubuntu 24.04 runner also installs `ffmpeg` and the [libturbojpeg runtime](https://packages.ubuntu.com/noble/libturbojpeg) for the native HA frontend. Install the pinned lab dependencies in a separate virtual environment:

```sh
python -m pip install -r tools/simplifi/requirements-recovery.txt
gh release download v0.20.1b1 --repo kivster/simplifi --pattern simplifi.zip --dir /tmp/simplifi-previous
gh release download v0.21.0b1 --repo kivster/simplifi --pattern simplifi.zip --dir /tmp/simplifi-current
python tools/simplifi/recovery_drill.py \
  --previous-archive /tmp/simplifi-previous/simplifi.zip \
  --previous-sha256 39075824353780ccc21206e5057b4fdd6374c9098464a7457b4316418df8d34e \
  --current-archive /tmp/simplifi-current/simplifi.zip \
  --current-sha256 c33405e314791c324158065856f67d93c2b108f8a1fb91063c61e3e9514efc50
```

The hashes bind this example to those two exact release assets. Obtain hashes independently for another trusted pair and review their compatibility first. The worker blocks non-loopback connections, uses the offline simulator and refuses an existing HA configuration. It does not import production credentials or mutate production storage. Run without Python's `-O` option because assertions enforce the acceptance checks.

The printed temporary directory retains the fictional configuration, archive, phase logs and a `report.json` on success. A failed phase exits nonzero and leaves evidence for inspection. These files are not uploaded by the workflow. The [Native recovery drill workflow](../.github/workflows/recovery.yml) runs the same script on Linux.

## Recorded acceptance

The [2026-10-18 Linux run](https://github.com/kivster/simplifi/actions/runs/39165326601) passed all 11 cold-process phases on Ubuntu 24.04, Python 3.14.8 and HA Core 2026.10.1. It tested the exact `0.20.1b1` → `0.21.0b1` release archives above, native Core restore, rollback to `0.20.1b1` and re-upgrade. The tested tooling commit is `698c5907c56fb9bf986b191d425a31a820578b09`.

All saved-state and ownership comparisons passed, including the fictional credential marker, HA account grants, both temporary controls, retained request identity, entity IDs, customized/unrelated dashboards and history. Every served card matched the selected archive's bytes. No duplicate simulated policy creation occurred. This evidence applies to that compatible release pair; it does not establish compatibility with arbitrary older versions.

This is a Core configuration recovery test with the recorder database excluded. Integration files come from release archives directly: the HACS UI and its install/update flow are a separate test. It does not prove HAOS/Supervisor/App restoration, real controller outage behaviour, physical-client traffic or Companion/Watch behaviour.
