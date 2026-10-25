# Yealink Fritzbox Phonebook Sync

![CI](https://github.com/otih/yealink-fritzbox-phonebook-sync/actions/workflows/ci.yml/badge.svg)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://otih.github.io/yealink-fritzbox-phonebook-sync/)

A lightweight server that bridges the gap between Fritzbox phonebooks and Yealink IP phones. It fetches phonebooks from a Fritzbox via its TR-064 SOAP interface, converts them to Yealink's remote-phonebook XML format, and serves them over HTTP for the phone to poll.

**Tested with:** Yealink AX83H Wi-Fi handset × Fritzbox 7530 AX (FritzOS 8.25), connected via Deutsche Giganetz SIP trunk. Should work with any Yealink phone supporting remote phonebooks and any Fritzbox with TR-064 enabled.

**Zero pip dependencies** — pure Python 3.8+ standard library. The Docker image is ~55 MB (Alpine-based).

## Why this exists

The Yealink AX83H advertises Google Contacts synchronization in its datasheet, but this feature no longer works. Google deprecated the legacy Contacts API v3 in 2021 and fully shut down "Less Secure Apps" (password-based access via CardDAV/CalDAV) by March 2025. The AX83H's Google sync relies on the old CardDAV protocol with basic authentication — which Google no longer supports. There is no firmware update from Yealink to add OAuth 2.0 support.

This leaves AX83H owners with a phone that can synchronize contacts from Google in theory, but not in practice.

The solution this project implements: use the Fritzbox as an intermediary. The Fritzbox maintains its own Google Contacts import (via OAuth, managed by AVM) and stores the synchronized contacts in its internal phonebook. This server reads those phonebooks via the Fritzbox TR-064 API and converts them to the Yealink remote-phonebook XML format — bypassing the broken Google sync entirely.

One could argue that implementing OAuth 2.0 directly in this server (talking to Google's People API) would be a more "native" solution. However, the Fritzbox-as-proxy approach has a decisive architectural advantage: **multi-source aggregation**. The Fritzbox can sync phonebooks from multiple independent sources — multiple Google accounts, CardDAV servers (e.g. Nextcloud), or other mail providers — each appearing as a separate Fritzbox phonebook. The Fritzbox handles all the OAuth flows, token renewals, and CardDAV negotiations. This server simply reads whatever phonebooks the Fritzbox has aggregated, without needing to know or care where the contacts originated. Implementing multi-provider OAuth plus CardDAV in this server would be significantly more complex and fragile, and would tightly couple the phonebook sync to specific upstream APIs that can change at any time.

```
Source 1 ──OAuth/CardDAV──┐
Source 2 ──OAuth/CardDAV──┤──→ Fritzbox (aggregates) ──TR-064 SOAP──→ this server ──HTTP──→ Yealink
Source 3 ──OAuth/CardDAV──┘
```

### Interfaces involved

| Hop | Protocol | Direction | Purpose |
|-----|----------|-----------|---------|
| Google → Fritzbox | OAuth 2.0 (managed by AVM) | Pull | Nightly contact sync into Fritzbox phonebook |
| Fritzbox → this server | TR-064 SOAP (HTTP Digest auth, port 49000) | Pull | `GetPhonebookList` + `GetPhonebook` to retrieve phonebook XML |
| Fritzbox → this server | HTTP (plain, port 49000) | Pull | Download the raw phonebook XML via the URL from `GetPhonebook` |
| This server → Yealink | HTTP (plain, port 8080) | Push (polled) | Yealink polls `/menu.xml` and `/contacts/<id>.xml` every ~6 hours |

The Fritzbox handles the complex OAuth dance with Google. This server handles the format conversion from Fritzbox XML to Yealink XML. The phone just polls an HTTP endpoint — no OAuth, no CardDAV, no Google API knowledge needed on the phone.

### Compatibility with Deutsche Giganetz

This setup works seamlessly alongside a Deutsche Giganetz (DGN) SIP trunk. The Fritzbox registers with DGN's SIP server (`tel.dgn.digital`) for telephony, while the phonebook sync operates entirely over the LAN via TR-064 — completely independent of the SIP registration. Whether you use DGN, Telekom, or any other SIP provider behind the Fritzbox, the phonebook sync is unaffected.

## Architecture

The server maintains an in-memory cache of the converted phonebook. The Yealink phone polls `/menu.xml` on its own schedule (typically every 6 hours). The server refreshes its cache from the Fritzbox on a configurable interval (default: hourly). If the Fritzbox is temporarily unreachable, the server continues serving the last-known-good phonebook and retries in the background.

## Quick start

### Option A: Docker (recommended)

The easiest way to run the server is with Docker Compose. The pre-built image is published to GitHub Container Registry automatically on every push to `main`.

**Pull-only setup (no clone needed):** download just the two files you need and start:

```bash
mkdir phonebook-sync && cd phonebook-sync
BASE=https://raw.githubusercontent.com/otih/yealink-fritzbox-phonebook-sync/main
curl -sO $BASE/docker-compose.yml
curl -sO $BASE/.env.example && mv .env.example .env
# Edit .env — set FB_USER, FB_PASSWORD, SYNC_SERVER_URL, SYNC_AUTH_USER, SYNC_AUTH_PASSWORD
nano .env

docker compose up -d          # pulls ghcr.io/otih/yealink-fritzbox-phonebook-sync:0.3.2
docker compose logs -f
docker compose down           # stop (graceful, ~1-2s)
```

**Or clone the repo** (needed for building from source):

```bash
git clone https://github.com/otih/yealink-fritzbox-phonebook-sync.git
cd yealink-fritzbox-phonebook-sync
cp .env.example .env
nano .env
docker compose up -d
```

The `docker-compose.yml` pins a concrete version by default (`0.3.2`) for reproducible deployments — switch to `latest` if you prefer automatic updates, or `build: .` to build from source.

### Option B: Kubernetes

```bash
# Create the secret with your Fritzbox credentials and phonebook auth
kubectl create secret generic fritzbox-creds \
  --from-literal=FB_USER=phonebook \
  --from-literal=FB_PASSWORD='your-password' \
  --from-literal=SYNC_AUTH_USER=phonebook \
  --from-literal=SYNC_AUTH_PASSWORD='your-auth-password'

# Adjust SYNC_SERVER_URL in k8s.yaml, then deploy
# (image is pulled automatically from GHCR — no build needed)
kubectl apply -f k8s.yaml

# Check status
kubectl get pods -l app=yealink-fritzbox-phonebook-sync
kubectl logs -l app=yealink-fritzbox-phonebook-sync -f
```

### Option C: Direct (for testing)

```bash
python3 yealink-fritzbox-phonebook-sync.py \
  --fritzbox-host fritz.box \
  --fritzbox-port 49000 \
  --fritzbox-user myuser \
  --fritzbox-password 'mypassword' \
  --listen-port 8080 \
  --refresh-interval 3600 \
  --server-url http://192.168.1.50:8080
```

### Configure the phone

On the Yealink web UI → **Directory → Remote Phone Book**:

| Field | Value |
|-------|-------|
| Remote URL | `http://<server-ip>:8080/menu.xml` (or `http://user:pass@<server-ip>:8080/menu.xml` with auth) |
| Display Name | `Fritzbox` |

Click **Confirm**. The phone downloads the phonebook immediately and caches it locally.

If HTTP Basic Auth is enabled (see [Access control](#access-control-http-basic-auth)), embed the credentials in the URL since the AX83H does not have separate username/password fields for remote phonebooks.

## Fritzbox prerequisites

### Enable TR-064

1. Fritzbox web UI → **Heimnetz → Netzwerk → Netzwerkeinstellungen**
2. Expand **Additional Settings** (*Erweiterte Einstellungen*)
3. Enable **Zugriff für Anwendungen zulassen** (*Allow access for applications*)
4. Apply. No reboot needed on modern FritzOS.

### Create a dedicated user

Fritzbox web UI → **System → Fritzbox-Benutzer** (*FRITZ!Box Users*):

1. Click **Add User** (*Neuer Benutzer*)
2. Set a username and password
3. Grant only **Zugang zu Inhalten aus dem Heimnetz** (*Access to contents in the home network*)
4. No internet access or admin rights needed

### Find your phonebook ID

The Fritzbox assigns integer IDs to each phonebook. To find out which IDs exist:

```bash
python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('m', 'yealink-fritzbox-phonebook-sync.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
c = m.FritzboxClient('fritz.box', 49000, 'YOUR_USER', 'YOUR_PASSWORD')
print('Phonebook IDs:', c.get_phonebook_ids())
"
```

Typically ID `0` is the default "Telefonbuch" and higher IDs are Google-imported phonebooks.

### Phonebook selection

The `FB_PHONEBOOK_ID` setting (or `--phonebook-id` flag) controls which phonebooks appear on the phone:

| Setting | Behavior on the phone |
|---------|----------------------|
| Single ID (e.g. `1`) | Only that phonebook appears — direct access, no selection menu |
| Multiple IDs (e.g. `0,1`) | Each phonebook appears as a separate selectable entry |
| Empty (unset) | All phonebooks are auto-detected and listed individually |

Each phonebook shows its name and contact count in the menu (e.g. "Work (193)"). Empty phonebooks — those containing only internal Fritzbox numbers like `**9` or `**600` — are automatically hidden from the menu.

## Configuration

All configuration is via environment variables. CLI flags override env vars but are rarely needed — the Docker container is fully controlled via `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `FB_HOST` | `fritz.box` | Fritzbox hostname or IP |
| `FB_PORT` | `49000` | TR-064 port |
| `FB_USER` | *(required)* | Fritzbox user with Heimnetz access |
| `FB_PASSWORD` | *(required)* | Fritzbox user password |
| `FB_PHONEBOOK_ID` | *(auto)* | Comma-separated phonebook IDs. Single = one entry; multiple = selectable list; empty = all |
| `SYNC_LISTEN_PORT` | `8080` | HTTP listen port |
| `SYNC_REFRESH_INTERVAL` | `3600` | Seconds between Fritzbox syncs |
| `SYNC_SERVER_URL` | *(required)* | URL the Yealink phone uses to reach this server |
| `SYNC_AUTH_USER` | *(empty)* | HTTP Basic Auth username — set to protect the phonebook |
| `SYNC_AUTH_PASSWORD` | *(empty)* | HTTP Basic Auth password |
| `SYNC_ALLOWED_IPS` | *(empty)* | Optional allowlist: comma-separated IPs or CIDR ranges; empty = allow all |
| `SYNC_LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `SYNC_LOG_FORMAT` | `text` | Log format: `text` or `json` (for log aggregation) |

**Important:** `SYNC_SERVER_URL` must be the address the **phone** uses to reach the server — not `localhost` or `0.0.0.0`. For Docker, use the host's LAN IP. For Kubernetes, use the Service name or an externally reachable address.

## Access control (HTTP Basic Auth)

By default the phonebook is served without authentication. To protect it, set `SYNC_AUTH_USER` and `SYNC_AUTH_PASSWORD` in your `.env`:

```bash
SYNC_AUTH_USER=phonebook
SYNC_AUTH_PASSWORD=aStrongPassword
```

The server enforces HTTP Basic Auth on all endpoints except `/health` (which is needed for Docker/K8s health checks and exposes no contact data).

On the Yealink phone, configure the same credentials. Depending on the model, there are two ways:

1. **Username/Password fields** (if available): Web UI → Directory → Remote Phone Book → Username / Password fields

2. **Embedded in the URL** (works on all models): include credentials directly in the Remote URL:
   ```
   http://phonebook:aStrongPassword@<server-ip>:8080/menu.xml
   ```

Without auth, anyone on the same network can read the full phonebook. **Setting auth is strongly recommended.**

### IP allowlist (optional)

Set `SYNC_ALLOWED_IPS` to restrict which clients may access the phonebook at all — single IPs or CIDR ranges, comma-separated:

```bash
SYNC_ALLOWED_IPS=192.168.1.0/24,10.0.0.5
```

Empty or unset (default) allows all clients. Blocked clients receive HTTP 403. The allowlist applies to all phonebook endpoints; `/health` and `/metrics` stay reachable (operational data only). Invalid values abort startup with a clear error.

### Auth rate limiting (automatic)

Failed Basic-Auth attempts are rate-limited per client IP: after 5 failures within 60 seconds, further attempts from that IP get HTTP 429 until the window expires. A successful authentication resets the counter. This is defense-in-depth for the (unlikely) case of brute-force attempts from the LAN.

### Fail-fast configuration validation

Invalid values (port ranges, non-numeric phonebook IDs, non-positive refresh intervals, unknown log levels, malformed allowlists) are rejected at startup with a clear error message instead of failing at runtime.

## HTTP endpoints

| Path | Content |
|------|---------|
| `/menu.xml` | YealinkIPPhoneMenu — lists all phonebooks as selectable entries |
| `/contacts/<id>.xml` | YealinkIPPhoneDirectory — contacts for a specific phonebook |
| `/health` | JSON status: `{"status":"ok","contacts":193,"last_sync_age_sec":42}` |
| `/metrics` | Prometheus metrics: `yfps_build_info` (version), `yfps_degraded` (server-computed staleness flag), Fritzbox-side sync counters/age, phone-side fetch counters/age (when did the phone last pull?), contact and phonebook counts. See [Metrics & Alerting](https://otih.github.io/yealink-fritzbox-phonebook-sync/metrics/) for the reference, Prometheus scrape config and suggested alert rules |

`/health` and `/metrics` are served without authentication (operational data
only, no contact details); all phonebook endpoints require HTTP Basic Auth
when configured.

## How it works

1. **SOAP `GetPhonebookList`** — retrieves the list of phonebook IDs from the Fritzbox via TR-064 (HTTP Digest auth on port 49000).
2. **SOAP `GetPhonebook`** — for each ID, retrieves a download URL.
3. **Download** — fetches each phonebook as raw XML (the same format the Fritzbox exports via its web UI).
4. **Convert** — transforms each Fritzbox phonebook into Yealink's `YealinkIPPhoneDirectory` format:
   - One `<DirectoryEntry>` per person
   - Multiple `<Telephone>` elements inside each entry if the person has several numbers
   - Each `<Telephone>` gets a `label` attribute mapped from the Fritzbox number type (Mobil, Festnetz, Arbeit, Fax, Sonstige)
   - Internal Fritzbox numbers (`**9`, `**600`, etc.) are filtered out
   - Contacts are sorted alphabetically (case-insensitive, umlaut-aware); contacts with the same name in one phonebook are merged into a single entry — the same name in different phonebooks stays separate
   - The phonebook name is extracted from the Fritzbox XML and used as the menu label
5. **Menu** — builds a `YealinkIPPhoneMenu` listing all non-empty phonebooks as selectable `<MenuItem>` entries, each showing the phonebook name and contact count (e.g. "Work (193)"). Each item links to its own `/contacts/<id>.xml` endpoint.
6. **Serve** — `/menu.xml` and `/contacts/<id>.xml` are served over plain HTTP (HTTP/1.1 with `Connection: close`).
7. **Refresh** — a background thread re-syncs from the Fritzbox every `SYNC_REFRESH_INTERVAL` seconds. If a sync fails (network error, Fritzbox reboot, etc.), the server continues serving the last-known-good data and retries on the next cycle.

### Technical note: raw sockets for TR-064

The Fritzbox TR-064 endpoint behaves unconventionally with Python's `http.client`: it sometimes returns HTTP 500 with a SOAP fault ("invalid action") instead of a proper HTTP 401 digest challenge. The server therefore uses raw IPv6 sockets to send the SOAP POST, read the 401 + `WWW-Authenticate` header, compute the digest response, and resend with authentication. This mirrors what `curl --digest` does internally. A retry loop handles the Fritzbox's inconsistency (sometimes 401, sometimes 500 on the first request).

## Vulnerability management (automated)

Three layers keep the published image safe around the clock:

1. **Build gate** — every image is Trivy-scanned (CRITICAL/HIGH, fixable)
   before it is pushed to GHCR; a finding blocks publication.
2. **Weekly re-scan** — Mondays 04:00 UTC the published `:latest` image is
   re-scanned against the current CVE database; findings open a labeled
   tracking issue automatically and the run goes red.
3. **Weekly rebuild** — Mondays 04:30 UTC (after the scan) the workflow
   compares the base-image digest recorded on the published `:latest`
   image (OCI label `org.opencontainers.image.base.digest`) against the
   current upstream `python:3.15-alpine` digest; on drift it re-runs the
   full CI pipeline as a called workflow — no commit to `main` involved —
   publishing fresh `:main` / `:latest` images if all gates pass. Version
   releases remain a human/AI-agent decision.

**Dependabot** opens update PRs weekly for GitHub Actions versions and the
Docker base image; every PR must pass the full CI (lint, types, tests,
E2E, coverage gate) before merging.

## Container hardening

The Docker image and Kubernetes manifests follow security best practices:

| Measure | Docker | Kubernetes |
|---------|--------|------------|
| Non-root user | `app` (UID auto-assigned) | `runAsUser: 1000` |
| PID 1 signal handling | `tini` | `tini` (in image) |
| Read-only root filesystem | `read_only: true` | `readOnlyRootFilesystem: true` |
| Dropped capabilities | `cap_drop: ALL` | `capabilities.drop: [ALL]` |
| No privilege escalation | `no-new-privileges` | `allowPrivilegeEscalation: false` |
| Health checks | Dockerfile `HEALTHCHECK` | `livenessProbe` + `readinessProbe` |
| Resource limits | — | `requests: 10m/32Mi`, `limits: 100m/64Mi` |
| Image size | ~55 MB (Alpine) | Same |

## systemd deployment (bare VM)

Create `/etc/systemd/system/yealink-fritzbox-phonebook-sync.service`:

```ini
[Unit]
Description=Yealink Fritzbox Phonebook Sync Server
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/yealink-fritzbox-phonebook-sync/yealink-fritzbox-phonebook-sync.py
Environment=FB_HOST=fritz.box
Environment=FB_PORT=49000
Environment=FB_USER=myuser
Environment=FB_PASSWORD=mypassword
Environment=SYNC_LISTEN_PORT=8080
Environment=SYNC_REFRESH_INTERVAL=3600
Environment=SYNC_SERVER_URL=http://192.168.1.50:8080
Environment=SYNC_AUTH_USER=phonebook
Environment=SYNC_AUTH_PASSWORD=mypassword
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Adjust paths and IPs, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now yealink-fritzbox-phonebook-sync
journalctl -u yealink-fritzbox-phonebook-sync -f   # follow logs
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|---------------------|
| `SOAP ... HTTP 401` | Wrong user/password, or user lacks Heimnetz permission |
| `could not obtain digest challenge after 5 retries` | Fritzbox unreachable, or TR-064 not enabled |
| `NewPhonebookList not found` | Fritzbox firmware too old, or unexpected response format |
| `713 SpecifiedArrayIndexInvalid` | Phonebook ID does not exist — check available IDs (see above) |
| Phone shows "Remote dir download fail" | Server unreachable from phone's subnet, or wrong `SYNC_SERVER_URL` |
| Phone shows empty phonebook | Sync hasn't completed yet — check `/health` endpoint |
| Phone shows "Telefonbuch (0)" with no contacts | Phonebook 0 contains only internal numbers — use `FB_PHONEBOOK_ID=1` to hide it |
| Old data after Fritzbox change | Phone caches remotely; force refresh by toggling the remote phonebook entry off/on in the Yealink web UI |

## Limitations

- **No contact photos:** The Fritzbox provides Google Contact photos as `<imageURL>` in its XML, but the Yealink remote-phonebook format does not support images. Photos are stripped during conversion.
- **Limited per-number type labels:** The Yealink remote-phonebook XML supports a `label` attribute on `<Telephone>` elements. The server maps Fritzbox number types to German labels (Mobil, Festnetz, Arbeit, Fax, Sonstige). Numbers without a type in the Fritzbox are shown without a label.
- **Plain HTTP only:** The server does not support TLS. On a trusted LAN this is fine. For TLS, place it behind a reverse proxy (nginx, Caddy, Traefik).
- **IPv6 preference:** The raw-socket SOAP client connects via IPv6 when the Fritzbox hostname resolves to AAAA records. This matches the Fritzbox's default behavior but may need adjustment if your network is IPv4-only.

## License

MIT — see [LICENSE](LICENSE).

## AI-generated content

The source code in this repository was predominantly generated by an AI assistant in collaboration with the copyright holder. The copyright holder reviewed, tested, and approved all generated code before publication.

This disclosure is provided for transparency and provenance purposes only. It does not alter the terms of the MIT License, nor does it grant or restrict any additional rights. The MIT License governs all use of this software.

## Contributing

Issues and pull requests welcome. Please test changes against a real Fritzbox + Yealink setup before submitting.
