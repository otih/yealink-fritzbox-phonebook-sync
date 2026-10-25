# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
