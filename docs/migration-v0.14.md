# Migrating to v0.14.0

v0.14.0 removes the last legacy configuration names. If you come from
v0.13.x, rename these environment variables before upgrading — the old
names have **no effect** anymore:

| Old name | New name |
|---|---|
| `FB_HOST` | `SYNC_FRITZBOX_HOST` |
| `FB_PORT` | `SYNC_FRITZBOX_PORT` |
| `FB_USER` | `SYNC_FRITZBOX_USER` |
| `FB_PASSWORD` | `SYNC_FRITZBOX_PASSWORD` |
| `FB_PHONEBOOK_ID` | `SYNC_FRITZBOX_PHONEBOOK_ID` |
| `SYNC_EXTERNAL_URL` | `SYNC_SERVER_URL` |

CLI flags are unchanged (`--fritzbox-host`, `--fritzbox-port`,
`--fritzbox-user`, `--fritzbox-password`, `--phonebook-id`) — only the
environment variable names changed. A deployment that passes CLI flags
in its command line needs no change at all.

## What happens if I forget one?

- **`SYNC_FRITZBOX_USER` / `SYNC_FRITZBOX_PASSWORD` missing:** the
  server exits with `Fritzbox user and password required.` — fail-fast,
  as designed.
- **`SYNC_FRITZBOX_HOST` missing:** falls back to the default
  `fritz.box` (same as before).
- **`SYNC_FRITZBOX_PHONEBOOK_ID` missing:** auto-detection in the
  background loop (same as before).
- **`SYNC_EXTERNAL_URL` set instead of `SYNC_SERVER_URL`:** the server
  warns about the missing server URL and builds menu URLs from the
  listen address — the phone will likely not reach it. Check the
  startup log for `--server-url not set`.

After renaming, run the one-shot diagnostic to verify:

```bash
docker run --rm --env-file your.env ghcr.io/otih/yealink-fritzbox-phonebook-sync:0.14.0 \
  --check
```

Exit 0 = the server can serve your configuration.
