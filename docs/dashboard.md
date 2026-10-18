# Dashboard setup

After configuring SimpliFi, open **Developer tools → Actions** and run `family_network.dashboard_configuration` with the integration's `entry_id`. The response contains `dashboard`, `resource` and entity bindings. Use the returned configuration for a new Home Assistant dashboard through its raw configuration editor.

The generated dashboard is native Lovelace, with a bundled custom card. It uses the existing `family-network-card` element and `family_network` actions.

For storage-managed Lovelace resources, integration setup registers the card and updates its versioned resource URL automatically. Exact old local URLs for this card are migrated using Home Assistant's resource collection API. Other resources and dashboard contents are preserved.

If your resources are configured in YAML, add the returned `resource` URL with `type: module`. Remove the previous resource entry for this card, if present, to avoid loading two versions. The bundled URL for this draft is:

```yaml
url: /family_network_static/family-network-card.js?v=0.18.0b1
type: module
```

Reload the browser or Companion app frontend after an integration update. The generated configuration uses your actual config entry and registered entities; do not substitute example IDs.
