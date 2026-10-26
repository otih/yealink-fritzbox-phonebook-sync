# Threat Model

The threat model for yealink-fritzbox-phonebook-sync, following
[CON.8.A21](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/IT-GS-Kompendium_Einzel_PDFs_2023/03_CON_Konzepte_und_Vorgehensweisen/CON_8_Software_Entwicklung_Edition_2023.pdf)
(BSI IT-Grundschutz). It is part of the development documentation
(CON.8.A12) and feeds the secure design decisions (CON.8.A22).

## Assets and protection needs

| Asset | Confidentiality | Integrity | Availability |
|-------|-----------------|-----------|--------------|
| Phonebook data (names, numbers — personal data of contacts) | high | high | normal |
| Fritzbox credentials (`FB_USER`/`FB_PASSWORD`) | high | high | normal |
| Phonebook HTTP credentials (`SYNC_AUTH_USER`/`SYNC_AUTH_PASSWORD`) | high | high | normal |
| TLS private key (`SYNC_TLS_KEY`) | high | high | normal |
| Service availability (the phone depends on it for its directory) | — | — | normal |
| Container/host integrity | — | high | high |

## Trust boundaries and data flow

```
Internet ──(never)──┐
                    │
 Fritzbox LAN ── TRUST BOUNDARY 1 (Fritzbox user credentials)
     │ SOAP/TR-064, Digest auth, port 49000 (also reachable for TLS-less
     │ HTTP download of the phonebook XML)
     ▼
 this server (container, non-root, read-only rootfs)
     │ in-memory cache + optional on-disk cache (SYNC_CACHE_DIR, 0600)
     ▼ ── TRUST BOUNDARY 2 (LAN clients: phones, any other LAN device)
 HTTP(S) on SYNC_LISTEN_PORT — /menu.xml, /contacts/<id>.xml, /all.xml,
 /health, /metrics
     ▼
 Yealink phone(s) — polls the remote phonebook
```

The server is designed for a trusted home/SOHO LAN. It is NOT designed
to be reachable from the internet — the README and the container
hardening (`cap_drop: ALL`, read-only rootfs, non-root user) reflect
that. Anyone who can reach the port can attempt to read the phonebook.

## STRIDE analysis per component

### 1. Fritzbox → server (SOAP fetch)

| Threat | Existing mitigation |
|--------|---------------------|
| **Spoofing** — a fake Fritzbox answers the SOAP call | TR-064 requires HTTP Digest auth with a dedicated Fritzbox user; the phonebook download URL is only accepted with `http(s)://` scheme (S310 exception documented) |
| **Tampering** — phonebook XML in transit | Trusted LAN segment; the XML is parsed with stdlib ElementTree without DTD/external-entity resolution (S314 exception documented); no pip dependencies means no transitive supply-chain code (CON.8.A6/A20) |
| **Repudiation** | Server logs every sync cycle and failure; log level/format configurable (`text`/`json`) for audit trails |
| **Info disclosure** | Credentials never logged; both are env-only (never in the project `.env`, per convention) |
| **DoS** | Retry loop with exponential backoff (max 5×0.3s per SOAP call, capped retry delay); last-known-good data keeps serving |
| **Elevation of privilege** | Server reads via a Fritzbox user limited to *Zugang zu Inhalten aus dem Heimnetz* — no admin rights required or used |

### 2. Server → phones (HTTP endpoints)

| Threat | Existing mitigation |
|--------|---------------------|
| **Spoofing** — a phone impersonates another | IP allowlist (`SYNC_ALLOWED_IPS`, opt-in); per-IP fetch tracking makes handsets distinguishable |
| **Tampering** — a MITM rewrites the served XML | Optional TLS (`SYNC_TLS_CERT`/`KEY`) hardened to SSL-Labs A+ style (TLS 1.2+, ECDHE+AEAD only, HSTS); without TLS the LAN must be trusted — documented risk acceptance, see below |
| **Repudiation** | Every request logged with client IP, path and status; auth failures and 429s counted in metrics |
| **Info disclosure** — phonebook read by unauthorized LAN devices | HTTP Basic Auth (opt-in but strongly recommended; see risk acceptance), embedded-credentials URLs for phones without auth fields, per-IP rate limiter (5 fails/60s → 429) as brute-force defense, auth failure/limit metrics + `PhonebookAuthBruteForce` alert |
| **DoS** — a hung/parallel client starves the server | ThreadingHTTPServer (a hung client cannot block `/health`); Docker HEALTHCHECK keeps restart semantics honest; healthcheck noise suppressed at DEBUG |
| **Elevation of privilege** | No write endpoints exist (GET-only surface); `/health` and `/metrics` expose operational data only — no contact data |

### 3. On-disk cache (`SYNC_CACHE_DIR`, opt-in)

| Threat | Existing mitigation |
|--------|---------------------|
| **Tampering** — someone edits the snapshot to poison the phonebook | File created `0600`, atomic write (`os.replace`); corrupt/unreadable snapshots are refused with a warning and never break startup; a tampered-but-valid snapshot is the operator's host-security concern (documented: bind-mount must be owned by the container UID) |
| **Info disclosure** — world-readable contact dump | `0600` on every snapshot; the docs instruct volume permissions (UID 1000 / named volume) |

### 4. Supply chain (build → image)

| Threat | Existing mitigation |
|--------|---------------------|
| **Tampering** — compromised dependency or base image | Zero pip dependencies (stdlib only); base image digest-pinned via `BASE_IMAGE_DIGEST` build-arg and OCI label; CI builds with SBOM attestation + SLSA provenance `mode=max`; Trivy gate blocks CRITICAL/HIGH (fixed) findings before publish; weekly re-scan of the published image with auto-issues; Dependabot for Actions/base image (CON.8.A8/A20) |
| **Repudiation** — untraceable image provenance | `yfps_build_info{version}` + OCI revision label on every image; each release tag maps 1:1 to a merge commit |

## Documented risk acceptances

These are conscious deviations from a strict secure-by-default posture,
accepted for the home/SOHO LAN context (the product's design target):

1. **HTTP Basic Auth is OFF by default.** BSI CON.8.A5 requires
   defaults that enable secure operation. We deliberately ship with
   auth unset because (a) the primary client — the Yealink AX83H — has
   no auth fields and requires credentials embedded in the URL, making
   the setup friction high, and (b) the deployment target is a trusted
   home LAN, typically behind NAT. The server logs a prominent warning
   at startup when auth is disabled. **Accepted risk:** any LAN device
   can read the phonebook while auth is unset. Mitigations available:
   `SYNC_AUTH_USER`/`PASSWORD`, `SYNC_ALLOWED_IPS`, TLS. This
   acceptance is revisited if the deployment model changes (internet
   exposure, multi-tenant networks).
2. **Plaintext HTTP by default (no TLS).** Same LAN argument; TLS is
   opt-in (`SYNC_TLS_CERT`/`KEY`) and the phone must trust the
   certificate — the trust management (public cert or CA rollout on the
   phone) is explicitly the operator's responsibility, documented in
   the configuration docs.
3. **Credentials embedded in the phone's remote URL** (required by the
   AX83H firmware, no separate auth fields). The URL — including the
   password — is stored on the phone and appears in the menu.xml
   served to it. Accepted for the LAN context; TLS protects the
   transport when configured.

## Review

This model is reviewed when: the trust topology changes (internet
exposure, reverse proxy in front), new endpoints or data flows are
added, or a security-relevant incident occurs. Every `feat`/`fix` PR
touches this file if it adds attack surface — same commit, per the
docs-are-part-of-the-feature rule.
