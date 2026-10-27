# Auto-Provisioning (Yealink)

For fleet deployments (several phones of the same model), configuring
each phone by hand in the web UI does not scale. Yealink phones fetch
their configuration from a provisioning server on boot and on demand
(FTP/TFTP/HTTP/HTTPS — see your model's auto-provisioning guide).

This page provides the phonebook-relevant snippets for a provisioning
configuration file. The example targets the **AX83H** (common CFG file
name `y000000000180.cfg`); other models use different common-CFG names
but the same parameter names.

## Phonebook snippet (common CFG)

```ini
#!version:1.0.0.1
# Yealink common configuration — phonebook-relevant settings only.
# Place the full file on your provisioning server; this excerpt shows
# the parts this project cares about.

# --- Remote phonebook 1: the Fritzbox-sync server -------------------------
# The URL the PHONE uses to reach the server (same as SYNC_SERVER_URL).
# With HTTP Basic Auth enabled, embed the credentials in the URL —
# the AX83H has no separate username/password fields for remote
# phonebooks:
features.remote_phonebook.url = http://phonebook:PASSWORD@192.168.1.50:8080/menu.xml
features.remote_phonebook.display_name = Fritzbox

# --- Caller-ID matching priority ------------------------------------------
# Which directory TYPES the phone searches for incoming/outgoing call
# matching, in order. 2 = local directory, 6 = remote phonebook.
# Unlisted or disabled directory types are skipped. Example: prefer the
# remote phonebook (this server) over the phone's local directory:
directory_setting.lookup_call_in.priority = 6,2
directory_setting.lookup_call_out.priority = 6,2

# --- Fetch interval ---------------------------------------------------------
# How often the phone re-downloads the remote phonebook, in minutes.
# The server refreshes its cache from the Fritzbox every
# SYNC_REFRESH_INTERVAL (default: hourly) — a phone fetch interval of
# 1440 (daily) or 360 (6h) is plenty for a home/SOHO phonebook.
features.remote_phonebook.fetch_interval = 360
```

## TLS variant

With `SYNC_TLS_CERT`/`SYNC_TLS_KEY` configured on the server, point the
URL at `https://` — and remember the documented requirement: **the
phone must trust the certificate** (publicly signed for a real
hostname, or your CA rolled out on the phone via provisioning):

```ini
features.remote_phonebook.url = https://phonebook.example.lan:8080/menu.xml
```

## How this fits together

- The provisioning snippet replaces the manual web-UI configuration
  described in the README (`Directory → Remote Phone Book`) — same
  values, mass-deployed.
- Everything else (which phonebooks appear, dedup, caching) is
  configured on the SERVER side via its env vars — see
  [Configuration](configuration.md).
- The caller-ID source behavior (why the display never shows the
  phonebook origin, what the priority list really controls) is
  documented in [Troubleshooting](troubleshooting.md#caller-id-shows-no-phonebook-origin-and-which-name-wins).

Model-specific parameter details (CFG file names, provisioning
transports, PnP) live in Yealink's admin guide for your phone model —
this page only covers the phonebook-relevant parts.
