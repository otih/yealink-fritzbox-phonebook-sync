# Configuration

All configuration is via environment variables. CLI flags override env
vars; in Docker deployments the `.env` file drives everything.

## Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `FB_HOST` | `fritz.box` | Fritzbox hostname or IP |
| `FB_PORT` | `49000` | TR-064 port |
| `FB_USER` | *(required)* | Fritzbox user with Heimnetz access |
| `FB_PASSWORD` | *(required)* | Fritzbox user password |
| `FB_PHONEBOOK_ID` | *(auto)* | Comma-separated phonebook IDs. Single = one entry; multiple = selectable list; empty = all |

## Server

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_LISTEN_PORT` | `8080` | HTTP listen port |
| `SYNC_REFRESH_INTERVAL` | `3600` | Seconds between Fritzbox syncs |
| `SYNC_SERVER_URL` | *(required)* | URL the Yealink phone uses to reach this server — not `localhost` or `0.0.0.0` |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_AUTH_USER` | *(empty)* | HTTP Basic Auth username; set both to enable auth |
| `SYNC_AUTH_PASSWORD` | *(empty)* | HTTP Basic Auth password |
| `SYNC_ALLOWED_IPS` | *(empty)* | Optional allowlist, comma-separated IPs or CIDR ranges; **empty = allow all** |

On the Yealink phone, embed the credentials in the Remote URL:
`http://user:pass@<server-ip>:8080/menu.xml` — the AX83H has no separate
auth fields for remote phonebooks, and the server embeds them
automatically into the Menu.xml URLs it serves.

## Persistence

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_CACHE_DIR` | *(empty)* | Directory for the persistent phonebook cache. **Empty (default) = disabled** — the pre-existing in-memory-only behavior. |

When set, the server persists the phonebook state after every
successful Fritzbox sync as a JSON snapshot (`phonebook-cache.json`,
created with `0600` permissions, written atomically) and restores it on
startup. This bridges container restarts while the Fritzbox is
unreachable: instead of the "Noch nicht synchronisiert" placeholder the
phone gets the last known good phonebook, and the next successful sync
overwrites the snapshot. A corrupt or unreadable snapshot is logged and
ignored — it never blocks startup.

For Docker deployments with `read_only: true`, mount a writable volume
at the `SYNC_CACHE_DIR` path, e.g.:

```yaml
    environment:
      SYNC_CACHE_DIR: /data
    volumes:
      - ./phonebook-cache:/data
```

## Contact dedup (optional)

Set `SYNC_DEDUP_CONTACTS` (or pass `--dedup-contacts`) to merge contacts
with the same name within one phonebook into a single entry — numbers are
combined, duplicate numbers collapse to one `<Telephone>` (first non-empty
label wins). Useful when the Fritzbox aggregates the same person from
multiple sources into one phonebook.

| Setting | Behavior |
|---------|----------|
| off (default) | Contacts pass through exactly as the Fritzbox delivers them (pre-0.8.0 behavior) |
| on | Same-name contacts in one phonebook merge into a single entry; duplicate numbers collapse |

Accepted values: `1`/`true`/`yes`/`on` enable it, `0`/`false`/`no`/`off`
or empty disable it. **Anything else aborts startup with a clear error**
(a typo must not silently disable the feature) — same fail-fast
philosophy as the other settings.

In both settings: contacts are always sorted alphabetically
(case-insensitive, umlaut-aware), and the same name in two different
phonebooks always stays separate (each phonebook is its own menu entry).

## Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `SYNC_LOG_FORMAT` | `text` | `text` or `json` (one JSON object per line, for log aggregation) |

## Validation

Invalid configuration fails fast at startup with a clear error: port
ranges (1–65535), non-numeric phonebook IDs, non-positive refresh
intervals, unknown log levels, malformed IP allowlists, and unrecognized
`SYNC_DEDUP_CONTACTS` values are all rejected before the server starts
listening.

`python3 yealink-fritzbox-phonebook-sync.py --version` prints the app
version and exits — handy in support cases (same source as the startup
banner and `yfps_build_info`).

## Diagnostic mode (`--check`)

`--check` (CLI only) answers "would this configuration serve a phonebook?"
in one shot: it connects to the Fritzbox, resolves or validates the
configured phonebook IDs, converts every phonebook and prints a summary
with contact counts — then exits with code 0 (OK) or 1 (problem found,
with hints). It never starts the HTTP server, so it is safe to run at
any time:

```bash
python3 yealink-fritzbox-phonebook-sync.py --check \
  --fritzbox-user YOUR_USER --fritzbox-password YOUR_PASSWORD
```
