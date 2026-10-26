# Contributing

Thanks for your interest in contributing!

> This document is the binding development guideline for this project
> (in BSI IT-Grundschutz terms: the "Richtlinie für die
> Software-Entwicklung" per CON.8.A11). It is kept current with the
> same discipline as code — changes to the process are PRs, too.

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
3. **Negative tests are mandatory, not optional.** Every new behavior
   ships with tests for what it must REJECT, in three categories:
   - **Config garbage:** for every new env var / CLI flag, ask "what is
     the dumbest value someone could type?" and test that it aborts
     startup with exit code 1 **and an error naming the variable**
     (see `tests/test_negative_config.py` for the pattern — a raw
     traceback that does not name the setting violates the contract).
   - **HTTP edge cases:** malformed headers, unknown paths, wrong IDs
     → the expected status code, never a crash.
   - **XML data garbage:** corrupt input, empty phonebooks, contacts
     without numbers → defined behavior instead of an exception.
   Positive tests alone prove the happy path — they would NOT have
   caught `SYNC_DEDUP_CONTACTS=treu` silently meaning "off" (found
   2026-10-26); the negative test would have.
4. **Keep the changelog current.** Every user- or security-relevant change
   gets its entry under `[Unreleased]` in `CHANGELOG.md` **in the same
   commit** as the change — never bundled later into the release.
5. **Docs are part of the feature.** Before finishing any change, check
   whether the README, the docs site (`docs/`), `.env.example`, or the
   CHANGELOG need updating — new config → `.env.example` +
   `docs/configuration.md` + README table; new endpoint/behavior → README +
   `docs/index.md`; user-visible change → CHANGELOG. Update them in the
   same commit as the feature.
6. **No breaking changes without a major version bump.** Existing env vars,
   CLI flags, XML output format, and HTTP endpoints must keep working.
   If a change is unavoidable, document it in the changelog and bump the
   major version.
7. **Test against real hardware before submitting.** At minimum: build the
   Docker image (`docker build .`) and check that the container boots and
   `/health` responds. Ideally, verify against a real Fritzbox + Yealink.

## Commit style

- Conventional commits (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`).
- The subject line states *what*; the body explains *why*.
- One logical change per commit.

## Branch names

Branches follow the Conventional-Branches scheme — the type prefix mirrors
the commit prefix, so branch, commits, and PR title tell the same story:

```
<type>/<issue-number>-<slug>     when an issue exists
<type>/<slug>                    otherwise
```

- **Types:** `feat`, `fix`, `docs`, `ci`, `test`, `refactor`, `chore`,
  `release` — identical to the commit prefixes (plus `release`).
- **Slug:** lowercase, hyphenated, short but descriptive
  (`fix/14-rate-limiter-hygiene`, `feat/threading-server`,
  `ci/pr-only-mode`, `release/v0.5.0`).
- A PR references its issue in the description (`Fixes #123`) — the number
  in the branch name is a reading aid, not a substitute.
- Feature/fix/docs branches base on and PR into `dev` (see
  [Branch model](#branch-model-dev--main)); `release/v<x.y.z>` branches
  carry the release commit into `dev` before the release PR.

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

## Branch model (dev → main)

Since 2026-10-26 the repository uses a two-branch model — `main` always
corresponds exactly to the last release:

- **`dev` — integration branch.** All feature/fix/docs PRs target `dev`.
  Every dev push publishes a `:dev` image to GHCR (through the full CVE
  gate) for testing on a host. `[Unreleased]` collects here.
- **`main` — release branch.** `main` receives changes **only** through
  the release PR (dev → main) and always carries `APP_VERSION` matching
  the latest tag. `:main` / `:latest` images are only ever release builds.

Release flow (the dev → main PR **is** the release):

1. Features merge into `dev` (squash) and collect in `[Unreleased]`.
2. When a release is due, the release commit (APP_VERSION bump,
   CHANGELOG section rename, image pins) lands **on dev**.
3. Open the dev → main PR, wait for green CI, **merge (never squash —
   squashing a long-lived-branch merge breaks the shared dev/main
   history; the next release PR would conflict)**.
4. Tag `v<x.y.z>` on the merge commit, wait for the tag build, create the
   GitHub release — after that, main, tag, image and APP_VERSION agree.

This replaces the previous "release per feature directly from main":
`APP_VERSION` on main can never lag behind the deployed code again, and
unreleased work never sits on the branch users watch.

## Pull requests

- **One PR per change** (binding): every feature, fix, docs change, CI
  change, hardening item ships as its OWN pull request — one PR is one
  referencable unit (changelog entries, issues and discussions link to
  it; "which PR introduced this?" must always have exactly one answer).
  Even small related items get separate PRs; a series is fine, batching
  is not. The release PR (dev → main) is the only aggregation point.
- PRs run the full CI: lint → tests → E2E container smoke test.
- Feature/fix PRs target `dev`; the only PR ever targeting `main` is the
  release PR.
- PRs never publish images; dev pushes publish `:dev`, main pushes publish
  `:main`/`:latest` — all behind the vulnerability gate.
- Reference the issue you fix (`Fixes #123`).

## Release approval checklist (Freigabeerklärung)

Every release is an approval decision, not just a merge. The release PR
author works through this checklist BEFORE opening the dev → main
release PR (in BSI IT-Grundschutz terms: the software release approval
per OPS.1.1.6.A4). The completed checklist — with the CI run links —
is the release's approval record; the GitHub release object documents
the outcome.

**Preconditions (block the release until all are green):**

- [ ] All planned `[Unreleased]` changes are on `dev` and CI is green
      on the dev HEAD (6/6 checks).
- [ ] Test results match expectations: unit tests pass on all matrix
      versions (3.13/3.14/3.15), E2E container smoke test green,
      coverage above the gate (60%).
- [ ] The vulnerability gate has passed for the code being released:
      Trivy found no unfixed CRITICAL/HIGH findings in the release build.
- [ ] Version bump is correct per the versioning table (breaking →
      MINOR in 0.x + changelog callout, feature → MINOR, fix/docs →
      PATCH) and matches the `[Unreleased]` entries.
- [ ] All four version pins agree: `APP_VERSION`, CHANGELOG section
      header, docker-compose image pin, README pull example (+ k8s.yaml
      if it changed since the last release).
- [ ] Docs are in sync: mkdocs builds strict-clean, the docs site
      reflects any changed behavior, the threat model was updated if
      the release adds attack surface.
- [ ] No open questions on the release PR; the maintainer has seen the
      release summary (surfaced in the conversation per the release
      authority rule).

**Maintainer-only items (cannot be automated; verify once, note in the
release PR):**

- [ ] Branch rulesets are active for `main` AND `dev` (6 required checks,
      force-push/deletion blocked).
- [ ] GitHub Pages deploy is healthy (docs.yml succeeded on main).

**After the merge (verification, not preconditions):**

- [ ] Tag on the merge commit, tag-CI green, version image verified in
      the registry (APP_VERSION inside the container), `:latest`
      revision label equals main HEAD.
- [ ] GitHub release object created LAST (after tag-CI green — the
      v0.9.0 lesson) with the CHANGELOG section as notes, `make_latest`.
