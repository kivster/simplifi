# Gateway load and controller traffic

Open **Activity → Administration → Gateway load** in the bundled SimpliFi card. This view requires an active Home Assistant administrator account. Access grants for household or agent controls do not expose site hardware telemetry.

The view lists adopted UniFi devices, with reported gateways first, followed by a device whose address matches the controller origin. A missing gateway flag is not inferred from a product name. Each row shows CPU and memory utilisation, load averages for 1, 5 and 15 minutes, uptime, connection state and the controller's sample timestamp. Unsupported or missing values display **Unknown**, including when zero would otherwise be misleading. A genuine zero remains zero.

Device statistics are read when you open or explicitly refresh the dialog. Reads share a 60-second cooldown across callers. There is no periodic statistics job, and the normal dashboard refresh does not fetch statistics. At most 64 devices and four simultaneous statistics requests are allowed, within a 30-second overall deadline. Pagination changes, duplicate identities, incomplete responses, offline devices and failed individual samples are shown as incomplete evidence. If a full read fails, the previous snapshot remains visibly last known. Samples older than two minutes, missing a timestamp or implausibly in the future are not fresh. Opening the dialog does not run a load test or change gateway policies.

The dialog is a snapshot. Its displayed sample ages and request counts reflect the time it was read; use **Refresh snapshot** to update them. Refreshing within the cooldown updates the cached projection and traffic counters without repeating the device reads.

## Request accounting

The five-minute request meter counts HTTP exchanges made by this SimpliFi instance: official Integration API requests, retries and the filtering/current-network reads that borrow HA's matching UniFi connection. Native session reauthentication and redirects triggered by those reads are included. The original UniFi client is not patched; its connection pool, cookies and TLS configuration are reused. Calls from the native UniFi integration itself, other applications, DNS observations and other SimpliFi instances are outside this meter's scope.

Counts include completed and in-flight requests, failed HTTP/network operations, cancelled requests, retries and HTTP 429 responses. Mean and maximum elapsed times cover completed request chains; retry backoff is excluded. Redirect exchanges are counted separately without inventing per-hop timings or concurrent requests. These measurements describe this integration's request workload, not the controller's total request rate or the cause of its CPU load. The device heartbeat can also predate the request that retrieved it.

Fixed endpoint templates replace site, device and policy identifiers. The meter never retains request URLs, keys, bodies, response bodies, headers or exception text. One-second buckets use a fixed endpoint vocabulary and expire after five minutes. Counts reset on integration reload. An aggregate INFO log is emitted at most once every five minutes while requests continue; it contains counts and fixed endpoint labels only.

Compact integration diagnostics include the cached request meter and device-read status/counts. Device names, identities and health samples are excluded from that diagnostic summary. Neither downloading diagnostics nor polling dashboard data causes controller health reads.

## Home Assistant action

`simplifi.gateway_health` returns the cached snapshot by default. Set `refresh: true` for an explicit device read subject to the shared cooldown:

```yaml
action: simplifi.gateway_health
data:
  entry_id: YOUR_SIMPLIFI_ENTRY_ID
  refresh: true
```

Run the action as an authenticated administrator. It does not advance the household revision, create an intent change, alter policies or request reconciliation. In the offline simulator, the device samples are clearly fictional and the physical-controller request count remains zero.
