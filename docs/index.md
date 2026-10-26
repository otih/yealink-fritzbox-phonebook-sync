# Overview

Welcome to the documentation of **yealink-fritzbox-phonebook-sync**.

A lightweight server that bridges the gap between Fritzbox phonebooks and
Yealink IP phones: it fetches phonebooks from a Fritzbox via TR-064 SOAP,
converts them to Yealink's remote-phonebook XML format, and serves them
over HTTP for the phone to poll.

The README on GitHub contains the full documentation — this page mirrors
it for convenient browsing.

## Quick facts

- **Tested with:** Yealink AX83H Wi-Fi handset × Fritzbox 7530 AX (FritzOS 8.25)
- **Zero pip dependencies** — pure Python 3.8+ standard library
- **Docker image:** ~55 MB (Alpine), multi-arch (amd64 + arm64), with SBOM attestation
- **License:** MIT

## Why this exists

The Yealink AX83H advertises Google Contacts synchronization, but this
feature no longer works: Google deprecated the legacy Contacts API v3
(2021) and shut down password-based CardDAV access ("Less Secure Apps")
by March 2025. The phone's sync relies on the old protocol with basic
authentication — unsupported, with no firmware update in sight.

This project uses the Fritzbox as an intermediary: the Fritzbox maintains
its own Google/CardDAV imports (OAuth managed by AVM) and aggregates them
into separate phonebooks. This server reads them via TR-064 and converts
them to the Yealink remote-phonebook format — source-agnostic, so any
contact source the Fritzbox supports works automatically.

## Where to go next

- **[Configuration](configuration.md)** — all environment variables
- **[GitHub README](https://github.com/otih/yealink-fritzbox-phonebook-sync#readme)** — full documentation
- **[CHANGELOG](https://github.com/otih/yealink-fritzbox-phonebook-sync/blob/main/CHANGELOG.md)** — release history

<!-- trigger-pages-deploy: GitHub Pages source is now GitHub Actions; re-run docs workflow -->

For the security architecture, documented risk acceptances and the STRIDE analysis per component, see the [Threat Model](threat-model.md).
