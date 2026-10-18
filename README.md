# SimpliFi

![SimpliFi](custom_components/family_network/brand/icon.png)

**Family internet controls for UniFi, made effortless via Home Assistant.**

SimpliFi brings people, shared devices, internet schedules and filtering controls into a native Home Assistant dashboard. It runs inside Home Assistant and talks to your local UniFi controller.

**Beta release.** Start with the offline simulator, then verify one explicitly selected device before using live management across a household.

## What it does

- Organise people and shared devices, with device assignment, discovery and optional quarantine for unassigned clients.
- Pause internet access, grant temporary allowances and apply scheduled internet, application, category and domain restrictions.
- Unblock a person's selected rules together, extend allowances and restore the saved rules when the allowance ends.
- Read network protection and other UniFi policies where the controller exposes them; show uncertain or stale observations explicitly.
- Run optional DNS observations from Home Assistant, with scheduled checks and retained results.
- Provide scoped access for existing Home Assistant accounts, activity history, configuration export/import and gateway recovery tools.
- Try the dashboard using an offline simulator before enabling gateway management.

The dashboard has Family, Devices, Rules, Filtering and Activity views. Its Lovelace card is bundled with the integration. No additional server or container is required.

## Installation

Requires Home Assistant 2026.10.1 or later for the currently validated development environment, plus a compatible UniFi Network local Integration API. Live features depend on the controller's endpoints, permissions and firmware. Start with the simulator or observation mode to check compatibility.

1. In HACS, add `https://github.com/kivster/simplifi` as a custom repository of type **Integration**.
2. Download **SimpliFi** and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → SimpliFi**.
4. Choose the simulator, or enter your local controller HTTPS origin and UniFi API key in the Home Assistant form. Select the managed networks, internet destination zone and household timezone.
5. Create the dashboard using the `family_network.dashboard_configuration` action. See [dashboard setup](docs/dashboard.md).
6. Assign devices and review the selected scope before enabling management.

For a manual installation, copy `custom_components/family_network` into your Home Assistant configuration directory and restart. The integration keeps this internal directory/domain for compatibility with existing installations.

Existing installations should follow [migration](docs/migration.md), including backup and rollback preparation.

## Updates

HACS manages release checks and installation. The Activity view shows the installed version and opens HACS. SimpliFi does not request a GitHub token, run Git Pull, update other integrations or restart Home Assistant automatically. Follow the restart prompt after an update.

## Interpreting status

Saved intent, gateway readback and a successful test on a device are different kinds of evidence. A confirmed policy does not prove that every application or traffic path is blocked. DNS observations originate from Home Assistant; they are not tests from a child's device.

Home Assistant must be running to reconcile changes and end temporary allowances. During an outage, the gateway retains its last applied policies; an allowance can outlast its deadline. Other UniFi policies and independent Home Assistant controls can also affect access.

## Development

Use Python 3.14 and the versions in `tests/family_network/requirements.txt`:

```sh
python -m pip install -r tests/family_network/requirements.txt
python -m pytest -q
python -m ruff check custom_components tests tools
python -m ruff format --check custom_components tests tools
python -m mypy
node --test tests/family_network/*.test.mjs
```

The code and original artwork use the [MIT license](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) and [release status](docs/release-status.md) for data sources and acceptance limitations.

Optional API contract tests use a separately acquired official schema: set `SIMPLIFI_UNIFI_OPENAPI` to its path. The document is not included in this repository.

SimpliFi is an independent community project. It is not affiliated with or endorsed by Home Assistant, the Open Home Foundation or Ubiquiti. Home Assistant, UniFi and Ubiquiti names identify compatible products.
