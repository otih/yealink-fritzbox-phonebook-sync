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

**Bind-mount permission note:** the container runs as the non-root `app`
user (UID 1000). A bind-mounted host directory must be readable (and
writable — snapshots are saved after each sync) by UID 1000:
`chown -R 1000:1000 ./phonebook-cache`. Named volumes handle this
automatically.

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

## TLS (optional)

Set BOTH `SYNC_TLS_CERT` and `SYNC_TLS_KEY` to serve the phonebook over
HTTPS instead of plain HTTP — strictly opt-in; unset (default) keeps the
unchanged plain-HTTP behavior.

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_TLS_CERT` | *(empty)* | Path to the PEM certificate file |
| `SYNC_TLS_KEY` | *(empty)* | Path to the PEM private key file |

One without the other, or a missing file, aborts startup with a clear
error naming the setting. Docker: mount cert and key read-only and set
the paths, e.g. `-v ./certs:/certs:ro -e SYNC_TLS_CERT=/certs/cert.pem
SYNC_TLS_KEY=/certs/key.pem`.

**Certificate trust is YOUR responsibility, not this tool's.** The
Yealink phone must trust the certificate it sees, otherwise it silently
fails to fetch the phonebook. Two supported ways:

1. **A publicly signed certificate** for a real hostname (e.g. from
   Let's Encrypt) — requires the phone to reach the server under that
   hostname and the CA chain (usually already trusted by the phone).
   Renewal/ACME is done OUTSIDE this tool (certbot, caddy, traefik —
   mount the renewed files; the server reads them on every start).
2. **Your own CA rolled out on the phone** — if the model supports
   importing a trusted CA. Not every firmware does; check your model's
   documentation before going this way.

A self-signed certificate WITHOUT a trusted CA will make the phone
reject the connection — test with a browser or `curl -v` first.

**TLS configuration (audited 2026-10-26, SSL-Labs A+ style):** the
server enforces TLS 1.2+ (explicit minimum — no reliance on library
defaults), accepts ONLY forward-secrecy AEAD suites
(ECDHE + AES-GCM / CHACHA20-POLY1305 — no CBC, no static-RSA key
exchange, no 3DES/RC4), and sends
`Strict-Transport-Security: max-age=31536000; includeSubDomains` on TLS
responses (HSTS protects browsers; the phone ignores the header).

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
