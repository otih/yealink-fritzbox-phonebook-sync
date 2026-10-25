# Contributing

Thanks for your interest in contributing!

## Development setup

```bash
git clone https://github.com/otih/yealink-fritzbox-phonebook-sync.git
cd yealink-fritzbox-phonebook-sync

# Lint + format (ruff — the CI enforces both)
ruff check yealink-fritzbox-phonebook-sync.py tests/
ruff format --check yealink-fritzbox-phonebook-sync.py tests/

# Unit tests (pure functions + HTTP handler with a local test server)
pytest tests/ -v
```

Both tools install with `pip install ruff pytest`.

## Ground rules

1. **Security scan before every commit.** `ruff check --select S,B` must pass
   on production code. If a finding must stay, document the risk acceptance
   at the code site (`# noqa: SZxxx — rationale`) — never silence silently.
2. **TDD for new features.** Write the failing test first
   (`tests/test_*.py`), then the implementation. The CI test matrix
   (Python 3.13/3.14/3.15) catches version-specific regressions.
3. **Keep the changelog current.** Every user- or security-relevant change
   gets its entry under `[Unreleased]` in `CHANGELOG.md` **in the same
   commit** as the change — never bundled later into the release.
4. **No breaking changes without a major version bump.** Existing env vars,
   CLI flags, XML output format, and HTTP endpoints must keep working.
   If a change is unavoidable, document it in the changelog and bump the
   major version.
5. **Test against real hardware before submitting.** At minimum: build the
   Docker image (`docker build .`) and check that the container boots and
   `/health` responds. Ideally, verify against a real Fritzbox + Yealink.

## Commit style

- Conventional commits (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`).
- The subject line states *what*; the body explains *why*.
- One logical change per commit.

## Versioning concept

This project follows [Semantic Versioning](https://semver.org/) with these
binding rules for choosing the next number:

| Change | Bump | Examples |
|--------|------|----------|
| **Breaking** — anything a user must adapt to: removed/renamed env vars, CLI flags, endpoints, changed XML output, changed default behavior | **MAJOR** (`1.0.0`) | removing `SYNC_SERVER_URL`, changing the `/contacts/<id>.xml` path scheme |
| **New feature** — new capability without breaking anything: new endpoints, new env vars (additive), new output that old consumers can ignore | **MINOR** (`0.3.0`) | `/metrics` endpoint, multi-arch images |
| **Fix / hardening** — bug fixes, security patches, dependency updates, CI/internal changes with no user-facing API change; also small additive conveniences | **PATCH** (`0.2.1`) | CVE cleanup in the image, SBOM attestation, backoff tuning |

Rules of application:

1. **`0.x` phase:** MAJOR-like breaking changes bump the MINOR number
   (0.x is explicitly "anything may change" in SemVer; we still treat it
   responsibly: 0.3.0 after v0.2.x never breaks silently — breaking
   changes are called out in the changelog).
2. **The artifact is the contract:** if the *published Docker image*
   changes, that is a release, even when the Python code did not —
   the image is the product users consume.
3. **Unreleased section decides:** the changelog's `[Unreleased]` entries
   determine the bump — a `feat:` entry forces MINOR, only `fix:`/`chore:`
   entries allow PATCH. If in doubt, take the higher number.
4. **Never rewrite history:** a released version is immutable; corrections
   get a new version.

The AI agent with release authority for this project applies exactly this
table; when a change does not clearly fit a row, it asks the maintainer.

## Pull requests

- PRs run the full CI: lint → tests → E2E container smoke test.
- The Docker image is only published from `main` after the vulnerability
  gate passes — PRs never publish.
- Reference the issue you fix (`Fixes #123`).
