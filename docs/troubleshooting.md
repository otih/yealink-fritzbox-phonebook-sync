# Troubleshooting

Symptom-first guide for the most common failure patterns. Every section
tells you what to run and which log lines or metrics answer the question.
`docker compose logs -f` (or `docker logs -f <container>`) is your friend
throughout — the server logs every decision it makes.

## First move: run `--check`

The `--check` diagnostic mode (see
[Configuration → Diagnostic mode](configuration.md#diagnostic-mode-check))
answers "would this configuration serve a phonebook?" in one command:

```bash
python3 yealink-fritzbox-phonebook-sync.py --check \
  --fritzbox-user YOUR_USER --fritzbox-password YOUR_PASSWORD
```

- **FAIL: cannot reach the Fritzbox** → continue with
  [Fritzbox unreachable](#fritzbox-unreachable) below.
- **FAIL: configured phonebook ID(s) … not in the Fritzbox phonebook list**
  → your `FB_PHONEBOOK_ID` references a phonebook that no longer exists;
  leave it empty (auto-detect) or use an ID from the printed list.
- **WARN: phonebook … 0 usable contacts** → the phonebook contains only
  internal Fritzbox numbers (`**9`, `**600`) — it is hidden from the menu
  by design; pick another ID or import contacts into it first.
- **Result: OK** → the server side is fine; the problem is between the
  server and the phone (see [Phone shows nothing](#phone-shows-nothing-or-noch-nicht-synchronisiert)).

## Phone shows nothing or "Noch nicht synchronisiert"

The phone displays the placeholder menu the server serves before its
first successful Fritzbox sync.

1. Run `--check`. If it fails, fix the Fritzbox side first.
2. Check `/health` — `"contacts":0` means no sync has succeeded yet:
   `curl http://<server>:8080/health`
3. Look for `Sync failed (retry N in Xs): …` in the logs — the message
   names the actual cause (auth, network, XML).
4. Once a sync succeeds, the phone needs to poll again: open the remote
   phonebook on the phone manually or wait for its poll interval
   (typically 1–6 h; configurable on the phone).

## Fritzbox unreachable

Typical log line:
`Sync failed: SOAP GetPhonebookList: could not obtain digest challenge after 5 retries: …`

In order of probability:

- **TR-064 disabled:** Fritzbox UI → Heimnetz → Netzwerk → Netzwerkeinstellungen
  → *Zugriff für Anwendungen zulassen* must be enabled.
- **Wrong user/permissions:** the Fritzbox user needs
  *Zugang zu Inhalten aus dem Heimnetz* — a plain "guest" account without
  it gets 401s forever.
- **FB_HOST resolves IPv6-only:** `fritz.box` resolves only via IPv6 in
  some networks; a container on a Docker bridge has no IPv6 and cannot
  reach it. Symptom: `Address family for hostname not supported`. Fix:
  `network_mode: host` for the container (IPv6 comes from the host), or
  use the Fritzbox's IPv4 address as `FB_HOST`.
- **Fritzbox rebooting / firmware update:** the server retries with
  exponential backoff and serves the last known good data — nothing to
  do, watch `yfps_sync_age_seconds` recover.

## Phone shows 401 / auth errors

The AX83H has no username/password fields for remote phonebooks —
credentials must be embedded in the Remote URL:

```
http://user:pass@<server-ip>:8080/menu.xml
```

Special characters in the password must be URL-encoded (`@` → `%40`,
`:` → `%3A`, …). The server logs `401` responses with the client IP;
`yfps_auth_failures_total` on `/metrics` counts them. Five failed
attempts from one IP within 60 s trigger the rate limiter (HTTP 429) —
if you locked yourself out, wait 60 s and fix the URL.

## Phone blocked with 403

`SYNC_ALLOWED_IPS` is set and the phone's IP is not in the list. The log
line `Blocked by IP allowlist: <ip>` names the rejected address. Add the
phone's IP/CIDR or clear the setting (empty = allow all).

## Phone shows stale data

Three separate clocks tell you where the staleness comes from
(see [Metrics & Alerting](metrics.md)):

| Metric | Meaning | If it grows … |
|--------|---------|--------------|
| `yfps_sync_age_seconds` | Fritzbox → server sync | Fritzbox unreachable / credentials broken; `yfps_degraded` turns 1 after 3× the refresh interval |
| `yfps_phonebook_fetch_age_seconds` | Phone → server fetch | Phone stopped polling: offline, reboot loop, wrong Remote URL, or it fetches from a different instance |
| `yfps_sync_failure_total` | Failed sync cycles | Rising = persistent Fritzbox-side problem |

Server-side staleness is the server's designed failure mode: it keeps
serving the last known good phonebook. With `SYNC_CACHE_DIR` set this
now also survives container restarts.

## Contacts missing or unexpected on the phone

- **Internal numbers are gone** (`**9`, `**600`): by design — they are
  not dialable from the PSTN side and are filtered out.
- **Duplicate contacts within one phonebook:** enable `SYNC_DEDUP_CONTACTS`
  (or `--dedup-contacts`) — same-name entries then combine into one with
  all their numbers. With dedup disabled (the default) contacts pass
  through exactly as the Fritzbox delivers them. The same name in two
  different phonebooks intentionally stays separate (each phonebook is
  its own menu entry).
- **A number looks different than in the Fritzbox:** the server strips
  formatting characters and the German `(0)` trunk prefix for reliable
  Caller-ID matching (`+49 (0)170 123456` → `+49170123456`).
- **Contact photos do not appear:** known firmware limitation — the
  remote phonebook XML has no photo element; only the phone's local
  directory supports avatars.

## Container restarts repeatedly

- `docker inspect --format '{{.State.Health.Status}}' <container>` and
  the HEALTHCHECK log lines tell you whether `/health` timed out. A
  single hung client must not cause this (threading server) — if you
  see it, please open an issue with the logs.
- Crash-on-start with `Configuration error: …` → the named env var is
  invalid; the message says which one and why.
- `Cannot create cache directory …` → `SYNC_CACHE_DIR` points somewhere
  not writable; mount a volume for it (root filesystem is read-only).

## Where to ask for help

Open a
[GitHub issue](https://github.com/otih/yealink-fritzbox-phonebook-sync/issues/new?labels=bug)
and include: the `--check` output (redact credentials!), the relevant
log lines, your Fritzbox model/FritzOS version, and the Yealink model +
firmware version.
