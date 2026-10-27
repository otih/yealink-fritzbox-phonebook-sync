# Security Policy

## Supported versions

This is a small hobby/SOHO project. Security fixes are applied to the
latest release only — there are no backports to older versions. Keep
your deployment on the most recent tagged image.

## Reporting a vulnerability

**Please do NOT report security vulnerabilities through public
GitHub issues.**

Report them privately via [GitHub security advisories](https://github.com/otih/yealink-fritzbox-phonebook-sync/security/advisories/new)
("Report a vulnerability" under the Security tab). That keeps the report
private to the maintainer and allows a coordinated fix + release.

Please include:

- a description of the issue and its impact (what an attacker can do),
- the affected version (the image tag or APP_VERSION you run),
- reproduction steps or a proof of concept,
- any relevant logs (redact credentials!).

## What to expect

- You will get an acknowledgement within 7 days.
- The issue is triaged: confirmed vulnerabilities are fixed with a
  PATCH or MINOR release, whichever the versioning rules require.
- Credit: if you wish, you are named in the release notes and the
  advisory. Coordinated disclosure timeline: 90 days max, shorter if a
  fix is ready.

## Scope notes

The [threat model](https://otih.github.io/yealink-fritzbox-phonebook-sync/threat-model/)
documents the intended deployment context: a trusted home/SOHO LAN.
Out of scope by design (documented risk acceptances, see the threat
model):

- plaintext HTTP by default (TLS is opt-in),
- HTTP Basic Auth disabled by default (setting auth is recommended and
  documented),
- exposure to the internet — this service is not designed for it.

Reports about these documented defaults will be treated as feature
requests, not vulnerabilities.

## Handling of past reports

Fixed security-relevant issues are listed in the CHANGELOG (Security
sections) and published via GitHub releases.
