# Metrics & Alerting

The server exposes Prometheus metrics on `GET /metrics` (no authentication —
safe to scrape from your monitoring host). The endpoint answers with the
classic `text/plain; version=0.0.4` exposition format.

Metrics are the observability contract of the 24/7 operation: they tell you
whether the phonebook is actually fresh (the phone silently shows stale data
otherwise) and whether the Fritzbox sync is healthy.

## Available metrics

| Metric | Type | Meaning |
|--------|------|---------|
| `yfps_build_info{version="x.y.z"}` | gauge | Build/version info, constant `1`. The `version` label carries the app version — use it to see which version a running instance reports (matches the startup log line). |
| `yfps_sync_success_total` | counter | Number of successful sync cycles since process start. |
| `yfps_sync_failure_total` | counter | Number of failed sync cycles since process start. |
| `yfps_sync_last_timestamp_seconds` | gauge | Unix timestamp of the last successful sync (`0` = never synced). |
| `yfps_sync_age_seconds` | gauge | Seconds since the last successful sync (`-1` = never synced). This is *the* freshness indicator. |
| `yfps_contacts_total` | gauge | Total contacts across all served phonebooks (after filtering). |
| `yfps_phonebooks_total` | gauge | Number of phonebooks currently served. |

**Interpretation guide:** `yfps_sync_age_seconds` should always be below your
refresh interval (default 3600 s). A rising `yfps_sync_failure_total` with a
growing age means the Fritzbox is unreachable (power outage, IP change,
credentials) — the phone keeps serving the *last known good* phonebook, so
users won't notice until you alert on it.

## Prometheus scrape config

```yaml
scrape_configs:
  - job_name: "yealink-phonebook-sync"
    scrape_interval: 60s        # freshness matters more than resolution here
    metrics_path: /metrics
    static_configs:
      - targets: ["phonebook-sync.lan:8080"]   # adjust host/port
        labels:
          service: "phonebook-sync"
```

## Suggested alert rules

Tuned for a 24/7 home/soho deployment — three severities:

```yaml
groups:
  - name: yealink-phonebook-sync
    rules:
      # Freshness: the phone silently serves stale data without this alert.
      # Fires when no successful sync happened for 2x the refresh interval
      # (default interval 1h -> alert after 2h).
      - alert: PhonebookSyncStale
        expr: yfps_sync_age_seconds > 7200 or yfps_sync_age_seconds == -1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Phonebook is stale ({{ $value }}s since last sync)"
          description: >-
            No successful Fritzbox sync for more than 2 hours. The phone
            serves the last known good phonebook. Check Fritzbox
            reachability and TR-064 credentials.

      # Sync failures: persistent failure even though syncs are attempted.
      - alert: PhonebookSyncFailing
        expr: increase(yfps_sync_failure_total[1h]) > 3
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Phonebook sync keeps failing"
          description: >-
            More than 3 sync failures in the last hour. The server retries
            with exponential backoff; if this persists, credentials or
            network path to the Fritzbox are broken.

      # Availability: the health endpoint is scraped implicitly by these
      # metrics — if the target is down, Prometheus marks it DOWN.
      - alert: PhonebookExporterDown
        expr: up{job="yealink-phonebook-sync"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Phonebook sync server unreachable"
          description: >-
            /metrics not reachable for 5 minutes — the container is down
            or the network path is broken. Phones cannot fetch an updated
            phonebook (stale data continues to be served from the phone's
            cache).
```

## Alertmanager routing example

```yaml
route:
  receiver: default
  group_by: [alertname, service]
  # Alerts for this service are rare; wait a bit so a transient
  # hiccup does not page anyone.
  group_wait: 5m
  group_interval: 30m
  repeat_interval: 12h

receivers:
  - name: default
    # Pick your channel; webhooks are the most universal.
    webhook_configs:
      - url: "http://homeassistant.lan:8123/api/webhook/phonebook-alert"
```

## Grafana quick check

For a one-panel dashboard, the essentials:

```promql
# Freshness over time
yfps_sync_age_seconds

# Success/failure rate (per 5 min)
rate(yfps_sync_success_total[5m])
rate(yfps_sync_failure_total[5m])

# Contacts served
yfps_contacts_total
```

## Version visibility

The startup log prints the running version as its second line:

```
2026-10-25 14:20:01,234 INFO  fritz-pb-sync: ============================================================
2026-10-25 14:20:01,234 INFO  fritz-pb-sync: yealink-fritzbox-phonebook-sync v0.5.0 starting
2026-10-25 14:20:01,234 INFO  fritz-pb-sync: Listening on http://0.0.0.0:8080
...
```

The same version is available as `yfps_build_info{version="…"}` on
`/metrics` — one `docker logs` glance or one PromQL query answers "which
version is actually running here?".
