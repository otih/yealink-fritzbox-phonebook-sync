# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`SYNC_EXTERNAL_URL` documented:** the legacy alias (pre-0.9.0
  name) has been accepted as a fallback for `SYNC_SERVER_URL` all
  along, but no doc mentioned it — anyone migrating an old
  deployment had to read the source. Now noted in .env.example and
  docs/configuration.md.
- **Error-path tests for the previously untested failure branches**
  (8 new tests): raw HTTP response parser contracts (empty response,
  missing separator, malformed status line, non-numeric status), the
  phonebook URL scheme refusal (file:// and ftp:// — the security
  path against a compromised Fritzbox), corrupt-book skip in the
  /all.xml merge, and the JSON log formatter output. Branch coverage
  77% -> 79%; **the CI gate ratchets 70 -> 75.**

### Fixed

- **Lint gates from v0.13.3 are actually active now.** The PR #77
  squash lost the pyproject `select` entries for `SIM`/`C4`/`PERF`/
  `RUF` (the findings had been fixed against a manual
  `--select SIM,C4,PERF,RUF` run, but the config change never
  landed — CI silently kept running without them). All four (plus
  the new C901) are in the selection now and the full gate is
  verified green.

### Changed

- **Complexity gate (C901, max 10) + hotspots refactored below it.**
  The five functions over the threshold — `convert_single_phonebook`
  (26!), `main` (19), `do_GET` (15), `build_all_xml` (12),
  `_raw_post` (11) — were decomposed into single-purpose helpers.
  Behavior identical: 159 tests + branch coverage green, mypy
  --strict green.

## [0.13.3] - 2026-10-30

### Changed

- **Coverage gate measures branches, not lines** (`--cov-branch` in
  CI): line coverage counts a line as covered when it executed —
  even if only one side of its `if` was ever tested. Branch coverage
  requires both paths. Current: 78% branch (gate stays 70); the
  number is harder-earned and the metric honest.

### Fixed

- **Python support floor made honest: 3.9+, not 3.8+.** README and
  docs claimed "pure Python 3.8+ standard library" while the code
  uses builtin generics (`dict[str, ...]`) — 3.9+ syntax. CI never
  tested 3.8. ruff's `target-version` moved py38 -> py39; the
  UP031/UP032 ignores (kept %-formatting) were re-justified as a
  deliberate style choice instead of a phantom 3.8 constraint.

### Changed

- **Simplification and perf rules now gated:** `SIM`, `C4`, `PERF`,
  `RUF` joined the lint selection. All 32 findings resolved: 12
  auto-fixed, 11 unused unpacked variables removed from tests,
  single-element slices to `next()` (RUF015), `contextlib.suppress`
  instead of try/except/pass (SIM105); three deliberate patterns
  carry per-line `# noqa` with rationale (per-book error isolation
  in `--check`, the polling loop, explicit metric-line formatting).

### Changed

- **mypy `--strict` is the new type gate.** All 15 strict findings
  fixed with explicit annotations and no behavior changes: precise
  generics instead of bare `dict`/`list`/`tuple` (the response dict
  is `dict[str, object]`, the dedup map is
  `dict[str, tuple[str, list[tuple[str, str]]]]`), `State` fields
  annotated (float timestamps — the implicit `int 0` defaults
  type-mismatched every `time.time()` assignment), boundary casts at
  `object`-typed dict lookups, `_resolve_host` normalizes getaddrinfo
  4-tuples to `(host, port)`. CI runs mypy --strict; pyproject sets
  `strict = true` so local runs match CI exactly.

### Changed

- **Security lint is now a CI gate, not a discipline.** The project
  rule demanded a `ruff --select S,B` scan before every commit, but
  nothing enforced it. ruff's bandit (`S`) rules now run in the lint
  job on every push. Accepted risks (0.0.0.0 bind, scheme-checked URL
  open, trusted-source XML parse, RFC 7616 MD5 digest) moved from
  scattered `# noqa` comments into ONE machine-readable `ignore`
  list in pyproject.toml with rationale comments; test-typical
  findings (asserts, dummy credentials, subprocess of the module
  under test) are per-file-ignored for `tests/`. The 11 in-code
  noqa comments remain as site documentation.
- **CI toolchain pinned via `requirements-dev.txt`** (ruff, mypy,
  pytest, pytest-cov): quality gates must be reproducible — unpinned
  installs let lint rules drift between runs, failing green commits
  or silently flagging less. Bumps go through PRs, same discipline
  as the Docker base image.

## [0.13.2] - 2026-10-29

### Fixed

- **Dual-stack socket resolution — plain IPv4 addresses work now.**
  The TR-064 socket was hardcoded `AF_INET6` because the author's
  network resolves fritz.box IPv6-only. For anyone else this broke
  EVERY sync: a plain IPv4 literal (192.168.179.1 — the Fritzbox LAN
  default) or a hostname without AAAA record crashed with
  "Address family for hostname not supported". New `_resolve_host()`
  resolves via `getaddrinfo(AF_UNSPEC)`, prefers IPv6 (author's
  network; v4-mapped ::ffff: literals keep working), falls back to
  IPv4. Negative test: unresolvable names raise the clean
  `socket.gaierror`, not the AF-family crash.
- **Non-blocking server boot (unmasked by the dual-stack fix).**
  `main()` called phonebook auto-detection and the initial sync
  SYNCHRONOUSLY before binding the HTTP port — the code comment
  claimed "non-blocking" for years while the call actually blocked.
  Invisible only because the IPv6-only socket crashed instantly on
  unreachable hosts; with working dual-stack timeouts a boot against
  an unreachable Fritzbox delayed /health by minutes — a Docker
  healthcheck would restart-loop the container. Detection and the
  initial sync now happen in the background sync loop (which already
  re-detects with backoff); boot time to /health measured 0.27s
  against an unreachable Fritzbox.

## [0.13.1] - 2026-10-29

### Added

- **README "Who this is for" section:** an honest scope statement —
  the exact niche (contacts on a Yealink phone, living on a Fritzbox,
  no manual maintenance), the cases this tool is NOT for (Broadsoft/
  LDAP environments, photo expectations, cloud-service expectations),
  and a fair comparison with the related approaches (dead Google sync,
  CardDAV converters, manual export). Helps the right people find it
  and the wrong people skip it.

### Added

- **Process-level E2E tests for `main()`** (`tests/test_main_process.py`):
  real subprocesses booting the actual server — startup with the
  version banner, /health + /metrics with the unreachable-Fritzbox
  degraded state, placeholder menu before the first sync, cache
  restore from `SYNC_CACHE_DIR` end-to-end (menu + contacts + health
  counts), and graceful SIGTERM shutdown (exit 0 within seconds).
  These pin the WIRING of main() — env parsing, server bootstrap,
  signal handling — as behavior tests. Note: subprocess coverage does
  not feed the coverage figure (the metric measures the test
  process), so the gate stays at 70 on purpose; the tests' value is
  behavioral, not statistical.

### Security

- **All GitHub Actions pinned to commit SHAs:** every external action
  reference (checkout, setup-python, upload-artifact, github-script,
  pages actions, docker actions, sbom-action, codeql-action — trivy
  was already pinned) now points at the exact commit SHA with the
  version tag in a comment, closing the gap between the project's
  base-image digest pinning and its own CI supply chain. A compromised
  moving tag can no longer execute in this repository's CI (the
  docker job holds `packages:write` credentials). The single
  remaining `@main` is the internal `workflow_call` into our own
  protected ci.yml — documented in place why a SHA there would break
  the base-drift rebuild. Dependabot continues to bump the pinned
  SHAs weekly.

## [0.13.0] - 2026-10-27

### Fixed

- **Race in phone-fetch tracking:** `_record_phone_fetch()` ran AFTER
  the response was written to the socket — a client (or metrics
  scrape) could observe the half-updated per-IP map. Root cause of
  the flaky bound test since v0.10.0 (only visible under slow
  execution, e.g. coverage mode): the tracking now runs BEFORE the
  response is served, making the fetch state consistent when the
  client returns.

### Added

- **"All contacts" menu entry:** `/menu.xml` now opens with an
  "All contacts" entry (total count across books, pointing at
  `/all.xml`), making the combined flat directory discoverable on
  menu drill-in phones like the AX83H — no need to know the URL.
  Absent when no phonebooks are served.

- **FritzboxClient test rig (mock sockets):** the SOAP/Digest path —
  raw IPv6 sockets, HTTP Digest per RFC 7616, the 401-or-500 challenge
  retry loop — is now covered by scripted-socket tests: digest
  computation verified against recomputed RFC hashes (with and without
  qop), the retry loop with the Fritzbox 500-then-401 quirk, the no-auth
  fallback, persistent network failure, and ID parsing. Two product
  quirks are now pinned as tests: the loop consumes ALL retries even on
  200-without-challenge (only exceptions short-circuit), and 500s
  without a challenge header end in the no-auth path with the last
  body — the exact behavior the inconsistent Fritzbox relies on.
  Coverage rises 64% → 76%; the CI gate ratchets 60 → 70.

- **Auto-provisioning guide** (`docs/provisioning.md`): a fill-in
  common-CFG snippet for Yealink provisioning (remote phonebook URL
  incl. embedded-auth form, caller-ID lookup priority
  `directory_setting.lookup_call_in/out.priority`, fetch interval) —
  the mass-deployment counterpart to the manual web-UI setup in the
  README, plus a TLS variant and links to server-side config and the
  caller-ID documentation.

- **Security policy (`SECURITY.md`):** private vulnerability reporting
  via GitHub security advisories (no public issues), expected handling
  (7-day acknowledgement, coordinated disclosure, credit), and scope
  notes that treat the documented risk acceptances (auth off, plaintext
  HTTP by default, LAN-only design) as feature requests, not
  vulnerabilities.

## [0.12.0] - 2026-10-26

### Changed

- **Auth-off-by-default is now a documented risk acceptance:** the
  README access-control section states the consequence (any LAN device
  can read the phonebook while auth is unset), links the threat model
  with rationale and revisit conditions, and names the mitigations.
  This closes the BSI CON.8.A5 gap (defaults must enable secure
  operation) the honest way: by formal acceptance instead of silence.

### Added

- **Threat model** (`docs/threat-model.md`, CON.8.A21): STRIDE analysis
  per component (Fritzbox fetch, HTTP endpoints, on-disk cache, supply
  chain), asset/protection-need matrix, trust boundaries — plus the
  first formal documentation of the accepted risks (auth off by
  default, plaintext HTTP by default, credentials embedded in the
  phone URL) with revisit conditions. Includes the OWASP pytm
  evaluation (not adopted; full 114-entry threat list walked against
  the model) and the log-integrity responsibility split (DE04).

- **Release approval checklist in CONTRIBUTING** (OPS.1.1.6.A4): the
  release PR author works through a formal precondition list before
  opening the dev → main release — CI green, test expectations,
  vulnerability gate, version-bump correctness, all four version pins,
  docs sync, maintainer-only items (rulesets, Pages), and the
  post-merge verification steps. CONTRIBUTING is now explicitly named
  as the binding development guideline per CON.8.A11.

- **Caller-ID source documentation:** the troubleshooting guide now
  explains why the phone display never shows WHICH phonebook a matched
  contact came from (firmware sees one remote-phonebook source), how
  the phone's directory-source priority
  (`directory_setting.lookup_call_in.priority` — a PHONE setting over
  directory types) decides which name wins across source types, and
  what to do when the same number exists in two Fritzbox phonebooks.

- **Grafana dashboard (`grafana/phonebook-sync-dashboard.json`):**
  importable dashboard covering all 13 exported metrics, grouped by
  question — Health & Version (up, version, degraded, sync age,
  success/failure rate), Phonebooks & Contacts (per-phonebook contact
  counts to spot a broken upstream import), Phones (fetch rate, fetch
  age per handset IP, last fetch timestamp), Security (rejected auth
  attempts, rate-limited requests). Expects the documented
  `yealink-phonebook-sync` scrape job name.

## [0.11.0] - 2026-10-26

### Added

- **`/all.xml` — combined flat directory:** all phonebooks merged into
  one YealinkIPPhoneDirectory, alphabetically sorted across phonebook
  boundaries. For phones with a single remote-phonebook slot where the
  menu drill-in is not usable. Same auth and fetch tracking as the other
  phonebook endpoints; cross-phonebook duplicates stay separate (dedup
  remains scoped to one phonebook).

- **Optional TLS (`SYNC_TLS_CERT` / `SYNC_TLS_KEY`):** set both to serve
  the phonebook over HTTPS; unset (default) keeps plain HTTP unchanged.
  One without the other or a missing file aborts startup naming the
  setting. **Certificate trust is documented as the operator's
  responsibility:** publicly signed certificate for a real hostname, or
  your own CA rolled out on the phone — ACME/renewal happens outside
  this tool (certbot/caddy/traefik in front, renewed files re-read on
  every start).

### Changed

- **One PR per change** (CONTRIBUTING): every feature, fix, docs or CI
  change ships as its own pull request — one referencable unit each.
  The release PR (dev → main) is the only aggregation point. The dev →
  main merge rule is now also documented as **merge, never squash**
  (squashing the long-lived-branch merge breaks the shared history —
  the v0.10.1 conflict lesson).

### Fixed

- **Per-IP fetch map bound is now deterministic:** the cardinality
  limit (10 most recent IPs) previously fired only on the NEXT
  recorded fetch — a map inflated externally (e.g. by test setup or a
  future cache restore) could exceed the limit indefinitely and leak
  into the /metrics scrape. The prune now runs on every recorded fetch
  AND defensively in the /metrics emitter, so the bound holds without
  requiring a follow-up fetch. Root cause of order-dependent CI flakes
  on the Python 3.15 matrix.

### Security

- **TLS hardened to SSL-Labs A+ style (audit 2026-10-26):** explicit
  TLS 1.2 minimum (previously only by library default), cipher suites
  restricted to ECDHE + AEAD (AES-GCM / CHACHA20-POLY1305) — removes
  static-RSA and CBC suites and with them the forward-secrecy gap; HSTS
  header (`max-age=31536000; includeSubDomains`) on TLS responses.
  Plain-HTTP mode (default) is untouched.

## [0.10.2] - 2026-10-26

### Fixed

- **Kubernetes manifest pinned a floating image:** `k8s.yaml` deployed
  `:latest` — violating the project's own reproducibility rule (the
  compose file pins a concrete version). It now pins the current release
  (`0.10.1`), and a new CI image-pin gate fails the build if any shipped
  manifest ever references `:latest` again.

### Changed

- **E2E coverage for `--check` and `SYNC_CACHE_DIR`:** the CI container
  smoke test now exercises the diagnostic mode (must exit 1 cleanly
  against a dead Fritzbox, never hang) and the persistent cache (a
  hand-crafted snapshot mounted into a fresh container with the Fritzbox
  dead must be served on `/menu.xml`).
- **Coverage gate raised 45% → 60%:** the suite reached 62% with the
  negative tests; the gate now ratchets so coverage can only go up.

## [0.10.1] - 2026-10-26

### Fixed

- **Integer env variables fail fast with the variable name:** garbage
  values like `FB_PORT=abc` crashed argparse construction with a raw
  Python traceback that never named the setting. They now abort with
  the same clean `Configuration error: Invalid FB_PORT value 'abc'
  (must be an integer)` as every other setting (`FB_PORT`,
  `SYNC_LISTEN_PORT`, `SYNC_REFRESH_INTERVAL`).

### Added

- **Negative-test suite (`tests/test_negative_config.py`):** every
  environment variable gets a garbage-value test — exit code 1 AND an
  error naming the variable, never a bare traceback. Codified in
  CONTRIBUTING.md as a mandatory practice (config garbage, HTTP edge
  cases, XML data garbage).

## [0.10.0] - 2026-10-26

### Added

- **Per-IP phone fetch metric:** `yfps_phonebook_fetch_age_seconds_by_ip
  {ip="…"}` on `/metrics` — which handset last pulled its phonebook
  (multi-handset setups), instead of only the aggregate over all phones.
  Bounded to the 10 most recently seen client IPs (cardinality safety).

- **Per-phonebook contact metric:** `yfps_phonebook_contacts{id="…",
  name="…"}` on `/metrics` — one gauge line per served phonebook. A
  shrinking source (e.g. a broken Google import into the Fritzbox) is
  now visible per phonebook instead of only in the global sum.
  Alert rule `PhonebookContactsDropped` documented (fires when a
  phonebook drops below 10 contacts while the server is healthy).

- **Runtime phonebook discovery (auto mode):** with `FB_PHONEBOOK_ID`
  unset, the sync loop re-detects the phonebook ID list on every cycle —
  a phonebook created on the Fritzbox (new Google account, CardDAV source)
  appears on the phone without a container restart. Explicitly configured
  IDs keep being used verbatim, as before.

- **`--version` flag:** prints the app version and exits — quick answer
  for support cases, same single source (`APP_VERSION`) as the startup
  banner and `yfps_build_info`.

### Fixed

- **`SYNC_DEDUP_CONTACTS` fail-fast validation:** a typo (e.g. `treu` or
  `ja`) previously meant a silent `off`. Unrecognized values now abort
  startup with a clear error — the same fail-fast contract as every
  other setting. Accepted: `1`/`true`/`yes`/`on` = enabled,
  `0`/`false`/`no`/`off`/empty = off.

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
