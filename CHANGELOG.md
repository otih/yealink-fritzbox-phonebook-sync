# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`SYNC_DEDUP_CONTACTS` fail-fast validation:** a typo (e.g. `treu` or
  `ja`) previously meant a silent `off`. Unrecognized values now abort
  startup with a clear error — the same fail-fast contract as every
  other setting. Accepted: `1`/`true`/`yes`/`on` = enabled,
  `0`/`false`/`no`/`off`/empty = off.

### Added

- **`--version` flag:** prints the app version and exits — quick answer
  for support cases, same single source (`APP_VERSION`) as the startup
  banner and `yfps_build_info`.

## [0.9.0] - 2026-10-26

### Changed

- **Contact dedup is now opt-in (`SYNC_DEDUP_CONTACTS`):** merging
  same-name contacts within one phonebook (and collapsing duplicate
  numbers) was always-on in 0.8.0 — it is now controlled by
  `SYNC_DEDUP_CONTACTS` (env) / `--dedup-contacts` (flag) and **off by
  default**: contacts pass through exactly as the Fritzbox delivers
  them (pre-0.8.0 behavior). Set `SYNC_DEDUP_CONTACTS=1` to keep the
  0.8.0 merging behavior. Alphabetical sorting (case-insensitive,
  umlaut-aware) remains always-on, as does the scoping: with dedup
  enabled, the same name in two different phonebooks stays separate.

## [0.8.0] - 2026-10-26

### Added

- **Sorted, deduplicated contacts:** directory entries are now sorted
  alphabetically (case-insensitive, German umlaut folding — "Ärger" sorts
  under A) and contacts with the same name in one phonebook merge into a
  single entry (numbers combined; duplicate numbers collapse to one
  `<Telephone>`, the first non-empty label wins). The same name in two
  different phonebooks stays separate — dedup is scoped to one phonebook.

- **Sync degradation flag:** `yfps_degraded` on `/metrics` is `1` when the
  last successful Fritzbox sync is older than 3× the refresh interval (or
  never synced), `0` otherwise — server-computed, so Prometheus does not
  need to know the interval. `/health` deliberately keeps answering
  `200 {"status":"ok"}` in this state: the server is fine, only the upstream
  sync is behind, and a restart would not help (it would even drop the
  last-known-good cache). Alert rule `PhonebookSyncDegraded` documented.

- **Brute-force visibility:** two new counters on `/metrics` —
  `yfps_auth_failures_total` (rejected Basic-Auth attempts) and
  `yfps_auth_rate_limited_total` (requests blocked with HTTP 429 by the
  per-IP rate limiter). The limiter itself is unchanged; it finally
  becomes observable. Alert rule `PhonebookAuthBruteForce` documented.

- **Optional persistent phonebook cache (`SYNC_CACHE_DIR`):** when set,
  the server writes its state after every successful Fritzbox sync to
  `phonebook-cache.json` (atomic write, `0600`) and restores it on the
  next startup. This bridges container restarts while the Fritzbox is
  unreachable: the phone gets the last known good phonebook instead of
  the "Noch nicht synchronisiert" placeholder. A corrupt snapshot is
  logged and ignored (never blocks startup); an un-creatable cache
  directory fails fast. Empty/unset keeps the previous in-memory-only
  behavior — fully backwards compatible.

- **Diagnostic mode `--check`:** one-shot first-setup verification —
  connects to the Fritzbox, lists the phonebook IDs (or validates the
  configured ones), converts every phonebook and prints name + usable
  contact count per ID, then exits 0 (OK) or 1 (with hints what to
  check). Never starts the HTTP server. Replaces the README's former
  copy-paste Python snippet for finding phonebook IDs.

### Added (docs)

- **Troubleshooting guide** (`docs/troubleshooting.md`, linked from the
  README): symptom-first walk-through of the most common failure
  patterns — placeholder menu, unreachable Fritzbox (incl. the
  IPv6-only `fritz.box` quirk), 401/403/429 on the phone, stale data
  (the three metric clocks), missing contacts, restart loops — each
  with the exact commands, log lines and metrics that answer it.
  Anchored on `--check` as the first diagnostic move.

## [0.7.0] - 2026-10-25

### Added

- **Phone-side fetch metrics:** `yfps_phonebook_fetch_total` (counter),
  `yfps_phonebook_fetch_last_timestamp_seconds` and
  `yfps_phonebook_fetch_age_seconds` (gauges) track when a phone last
  downloaded a phonebook (`/menu.xml` or `/contacts/<id>.xml`) — the
  phone-side mirror of the Fritzbox-side sync metrics. Alert rule
  `PhonebookNotFetchedByPhone` documented: a growing fetch age while the
  server is healthy means the phone stopped polling.

## [0.6.0] - 2026-10-25

### Added

- **Version in the startup log:** the server logs
  `yealink-fritzbox-phonebook-sync v0.6.0 starting` as its first banner
  line — `docker logs` now answers "which version is running?" at a
  glance. The version lives in a single `APP_VERSION` constant.
- **`yfps_build_info{version="…"}` metric:** the running version is
  exposed on `/metrics` (constant gauge `1`), so the deployed version is
  also visible in Prometheus/Grafana.
- **Metrics & Alerting documentation:** new docs page with the metric
  reference, a Prometheus scrape config, suggested alert rules (stale
  phonebook, persistent sync failures, server down) and an Alertmanager
  routing example.

## [0.5.0] - 2026-10-25

### Changed

- **PR-only mode:** `main` is protected by a GitHub ruleset (block force
  pushes, restrict deletions, require the 6 CI status checks on every
  ref update). Direct pushes are no longer possible; every change lands
  via pull request. The weekly rebuild workflow no longer commits the
  base-image digest to `main` — it reads the digest from the OCI label
  on the published image, and on drift re-runs the full CI pipeline as
  a called workflow (same lint/tests/E2E/CVE gates, then publish). The
  `.github/base-image-digest` file is gone.
- **CVE gate scans the actual build:** the Docker job now builds a
  dedicated `yfps/ci:scan-target` tag and points SBOM generation and
  the Trivy gate at it. Previously the gate could scan the stale
  registry `:latest` after base-image drift (and on PR runs the local
  tag shadowed the registry image), silently verifying old bits.

### Fixed

- **Base-digest label:** the double `sha256:` prefix in
  `org.opencontainers.image.base.digest` (published images carried
  `sha256:sha256:…`) is fixed at the source in CI; the rebuild
  workflow normalizes old labels when comparing digests.

## [0.4.1] - 2026-10-25

### Added

- **Threading HTTP server (24/7):** requests are served in parallel —
  a hung client (e.g. a phone with a dropped connection) can no longer
  block `/health` and other clients, which previously risked Docker
  health-check restart loops. Regression-tested with a concurrency suite
  (20 parallel requests alongside a deliberately hung socket).
- **Rate-limiter memory hygiene (24/7):** expired per-IP failure entries
  are cleaned up globally on each failure, keeping the dict bounded in
  long-running deployments.
- **Weekly base-image rebuild workflow:** Mondays 04:30 UTC (after the
  vulnerability scan) the workflow detects a moved `python:3.15-alpine`
  digest, commits the new digest, and thereby triggers the full CI —
  fresh images flow through the usual tests and CVE gate to `:main` /
  `:latest`. Version releases stay an explicit decision.
- **Dependabot:** weekly update PRs for GitHub Actions versions and the
  Docker base image, each subject to the full CI pipeline.
- **Soak test (evidence, not CI):** 2000 requests, 50 parallel clients,
  0 failures, 848 req/s, p95 57ms, 0 container restarts — verified
  against the locally built container.

### Changed

- README documents the three-layer vulnerability management (build gate,
  weekly re-scan, weekly rebuild) and Dependabot.

## [0.4.0] - 2026-10-25

### Added

- **Type annotations + mypy in CI:** full type coverage of the codebase,
  statically checked in the lint job — catches integration bugs the tests
  cannot see.
- **Test coverage gate:** CI runs pytest with coverage and enforces a
  minimum (currently 45%, the honest current level; the gate ratchets up
  as coverage grows). Tests load the dash-named module via a clean
  import name registered in `conftest.py`.
- **Fail-fast configuration validation:** invalid ports, non-numeric
  phonebook IDs, non-positive refresh intervals, and unknown log levels
  abort startup with a clear error instead of failing at runtime.
- **`SYNC_LOG_LEVEL`:** runtime-selectable log level (DEBUG, INFO,
  WARNING, ERROR, CRITICAL) without rebuilding.
- **`SYNC_LOG_FORMAT=json`:** one JSON object per line (timestamp, level,
  logger, message, exception) for log aggregation.
- **Auth rate limiting (automatic):** 5 failed Basic-Auth attempts per IP
  within 60 seconds lead to HTTP 429; success resets the counter —
  defense-in-depth against brute force from the LAN.
- **Optional IP allowlist (`SYNC_ALLOWED_IPS`):** comma-separated IPs or
  CIDR ranges; **empty/unset allows all clients** (fully backwards
  compatible). Blocked clients receive HTTP 403; `/health` and `/metrics`
  remain reachable.
- **Pull-only quick start:** README shows a two-file setup (compose +
  .env via curl) for users who do not want to clone the repo.
- **Documentation website:** MkDocs-based GitHub Pages deployment
  (overview + configuration reference) with a strict build in CI and a
  docs badge in the README.

### Changed

- **docker-compose.yml now pins a concrete image version** (`0.3.2`)
  instead of `latest` — reproducible deployments; switching to `latest`
  or `build: .` remains documented.
- **New optional env vars in compose/.env.example:** `SYNC_LOG_LEVEL`,
  `SYNC_LOG_FORMAT`, `SYNC_ALLOWED_IPS`.

### Security

- All new endpoints/features reviewed with `ruff --select S,B` — clean;
  no new exceptions were needed.

## [0.3.2] - 2026-10-25

### Fixed

- **E2E smoke test tested the wrong configuration:** the CI container
  started without `SYNC_AUTH_USER`/`SYNC_AUTH_PASSWORD`, so auth was
  correctly disabled and the 401 assertion failed on a 200. The E2E job
  now enables auth (productive configuration) and asserts both sides:
  unauthenticated → 401, correct credentials → 200.

## [0.3.1] - 2026-10-25

### Changed

- **Code of Conduct §4 rewritten:** the AI agent for this project holds
  release authority (merge, release, tag) — project-specific, does not
  transfer to other projects; every release decision is surfaced in the
  conversation.
- **Versioning concept added to CONTRIBUTING.md:** binding SemVer table
  (breaking → MAJOR, feature → MINOR, fix/hardening → PATCH) plus rules:
  0.x phase maps breaking to MINOR, image changes are releases, the
  [Unreleased] entries determine the bump, released versions are immutable.

## [0.3.0] - 2026-10-25

## [0.3.0] - 2026-10-25

### Added

- **Exponential backoff on sync failures:** after a failed Fritzbox sync the
  retry delay now grows (60s, 120s, 240s, …) capped at the refresh interval;
  a successful sync resets it. A Fritzbox reboot recovers within minutes
  instead of after the full hour.
- **Prometheus metrics endpoint (`/metrics`):** sync success/failure counters,
  last-sync timestamp and age, contact and phonebook counts in text
  exposition format. Served without auth (operational data only).
- **Phone-number normalization:** formatting characters (spaces, dashes,
  slashes, parentheses, dots) are stripped from phone numbers before serving,
  and the German "(0)" trunk-prefix notation inside international numbers is
  resolved (+49 (0)170… → +49170…) — improves exact Caller-ID matching on
  the phone. SIP URIs are left untouched.
- **HTTP handler test suite:** 12 tests exercising the real HTTP server —
  auth enforcement (correct/wrong/malformed credentials), URL routing
  (404s, numeric contact IDs), and the metrics endpoint.
- **E2E smoke test in CI:** builds the image, boots a container against an
  unreachable Fritzbox, and verifies /health, /metrics, auth rejection, and
  graceful SIGTERM shutdown — catches Dockerfile and entrypoint regressions
  the unit tests cannot see.
- **Multi-arch images:** CI now publishes linux/amd64 and linux/arm64
  (Raspberry Pi and other ARM hosts).
- **Contributing guidelines (`CONTRIBUTING.md`)** and **issue templates**
  (bug report, feature request).
- **Code of Conduct for AI-assisted development (`CODE_OF_CONDUCT.md`):**
  binds human and AI contributors alike — honesty about provenance,
  verification before claiming success, no undocumented security
  exceptions, human oversight for merges and releases.
- **CI status badge** in the README.

### Changed

- **Backwards-compatible only:** no env var, CLI flag, XML output, or
  endpoint changes; `/metrics` is a pure addition.

## [0.2.1] - 2026-10-25

### Changed

- **SBOM attached to the image itself:** CI now pushes images with the
  CycloneDX SBOM attached as an OCI attestation (referrer manifest) in the
  registry, retrievable with standard tooling (`docker buildx imagetools`,
  oras, Trivy) by anyone who pulls the image. SLSA build provenance is
  attached alongside. The downloadable workflow artifact remains for
  convenience.

## [0.2.0] - 2026-10-25

### Added

- **Base-image provenance labels:** the Docker image now records what it is
  built on via OCI labels — `org.opencontainers.image.base.name`,
  `base.digest` (exact base-image build, resolved and pinned by CI), and
  `base.version`. Visible via `docker inspect`. Local builds without CI
  set the digest label to empty.
- **SBOM as build artifact:** CI generates a CycloneDX software bill of
  materials for each build and attaches it as a workflow artifact — a
  complete, auditable component inventory including the base-image
  relationship.

## [0.1.2] - 2026-10-25

### Security

- **Container image CVE cleanup:** the published image now passes a Trivy
  scan with zero CRITICAL/HIGH findings. Previously the `python:3.15-alpine`
  base image bundled vulnerable pip packages (CRITICAL certifi
  GHSA-6q48-6c7w-9gw2; HIGH setuptools CVE-2025-47273, urllib3
  CVE-2026-97687/CVE-2026-97689, msgpack GHSA-6v7p-g79w-8964). The build
  now upgrades them and removes pip (a build-time tool whose vendored
  copies are not reachable by upgrades) from the runtime image.
  The application code itself was never affected — none of these packages
  are imported at runtime.

### Added

- **Vulnerability scanning, two layers:**
  - Build gate in CI: images are built, Trivy-scanned (CRITICAL/HIGH,
    fixable only), and only pushed to GHCR if the scan passes.
  - Weekly re-scan of the published `:latest` image (CVE databases change
    daily), with SARIF upload to the GitHub Security tab.
- **Automatic tracking issue:** when the weekly scan finds fixable
  CRITICAL/HIGH vulnerabilities, a labeled GitHub issue is opened
  automatically (no duplicates while one is open), so findings cannot
  silently rot in the Actions tab.

### Changed

- `trivy-action` is pinned to a commit SHA (supply-chain protection).

## [0.1.1] - 2026-10-25

### Security

- **Fixed:** URL scheme whitelist in `fetch_phonebook()` — the download URL
  from the SOAP response is now validated to be `http://` or `https://`.
  A tampered SOAP response can no longer trick the server into opening
  `file://` or other schemes (ruff S310).
- **Audited:** Full security scan (ruff S/B rules) with risk-based review.
  All remaining findings are documented exceptions with rationale at the
  code site:
  - MD5 in HTTP Digest auth — required by RFC 7616, protocol computation,
    not password hashing (S324, 4×).
  - stdlib XML parsing of Fritzbox responses — trusted authenticated LAN
    device; ElementTree does not resolve external entities, and the Fritzbox
    never emits DTDs, so XXE is not practically reachable (S314, 3×).
  - `0.0.0.0` binding is intentional — the Yealink phone must reach the
    server from the LAN (S104).
- **New project principle:** a security scan must pass before every commit;
  every exception is documented — risk-based approach.

### Added

- Unit test suite (`tests/test_converter.py`): 21 tests covering the XML
  converter, menu builder, placeholder menu, escaping helpers, and type
  label mapping.
- Ruff lint and format configuration (`pyproject.toml`) targeting
  Python 3.8 compatibility.
- CI pipeline (`.github/workflows/ci.yml`, renamed from `docker.yml`) with
  three gated jobs: `lint` (ruff check + format) → `test` (pytest matrix on
  Python 3.13/3.14/3.15) → `docker` (build and push to GHCR only when
  lint and tests pass).

### Changed

- Internal code cleanup to pass ruff: import sorting, unused imports
  removed, `raise ... from None` for exception clarity, ruff formatter
  applied. No functional changes.

## [0.1.0] - 2026-10-19

### Added

- Fritzbox TR-064 SOAP client with HTTP Digest authentication
- Conversion from Fritzbox phonebook XML to Yealink remote-phonebook XML format
  (`YealinkIPPhoneDirectory` with `DirectoryEntry` / `Telephone` elements)
- Multi-phonebook support: each Fritzbox phonebook appears as a selectable
  menu entry (`YealinkIPPhoneMenu`) with name and contact count
- Phonebook selection via `FB_PHONEBOOK_ID` (single, multiple, or auto-detect all)
- Number type labels mapped from Fritzbox types (Mobil, Festnetz, Arbeit, Fax, Sonstige)
- Internal Fritzbox numbers (`**9`, `**600`, etc.) automatically filtered out
- HTTP Basic Auth for access control (`SYNC_AUTH_USER` / `SYNC_AUTH_PASSWORD`)
- Auto-embedded credentials in Menu.xml URLs for phones without auth fields
- HTTP/1.1 server with `Connection: close` for Yealink compatibility
- Health check endpoint (`/health`) for Docker and Kubernetes
- Access logging to stdout (health checks suppressed)
- Graceful shutdown via SIGTERM/SIGINT (compatible with `docker stop`)
- Background sync thread with automatic retry on failure
- Last-known-good serving: continues serving cached data if Fritzbox is unreachable

### Infrastructure

- Alpine-based Docker image (~55 MB), non-root user, `tini` PID 1
- Read-only root filesystem, all capabilities dropped, no privilege escalation
- Docker Compose with security hardening and host networking
- Kubernetes manifests with Pod Security Context, probes, and resource limits
- GitHub Actions CI/CD pipeline building and publishing to GHCR
- Pre-built image available at `ghcr.io/otih/yealink-fritzbox-phonebook-sync:latest`

### Tested

- Yealink AX83H Wi-Fi handset × Fritzbox 7530 AX (FritzOS 8.25)
- Deutsche Giganetz SIP trunk (phonebook sync independent of SIP provider)
- 4 phonebooks, 411 total contacts (Google × 2, CardDAV/Nextcloud × 1, internal × 1)
- Docker container with host networking
- Graceful shutdown, network failure recovery, auth enforcement

### Documentation

- README with architecture overview, interface table, and multi-source explanation
- Setup guides for Docker, Kubernetes, and bare-metal systemd
- Fritzbox prerequisites (TR-064, dedicated user, phonebook ID discovery)
- Troubleshooting table, limitations, and container hardening matrix
- MIT License with AI-generated content notice
