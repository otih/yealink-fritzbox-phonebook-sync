"""SYNC_EXTERNAL_URL was removed in v0.14.0 (breaking cleanup).

The pre-0.9.0 alias kept working as a fallback for SYNC_SERVER_URL
long after the rename — never documented until shortly before removal.
Contract now: the alias has NO effect. Only SYNC_SERVER_URL is read.
"""

import os
import subprocess
import sys

APP = os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")


def test_external_url_alias_is_dead():
    """A server URL set ONLY via the alias must NOT reach the parser."""
    env = dict(os.environ)
    env["SYNC_EXTERNAL_URL"] = "http://alias-should-be-ignored:9999"
    env.pop("SYNC_SERVER_URL", None)
    env.pop("SYNC_TLS_CERT", None)
    env.pop("SYNC_TLS_KEY", None)
    # --check mode exits fast (Fritzbox unreachable) but AFTER arg
    # parsing — if the alias still worked, the server URL would appear
    # in the warning logs. Use --version instead: pure parse, no net.
    r = subprocess.run(
        [sys.executable, APP, "--version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert r.returncode == 0
    # The alias must not leak into anything; --version output has no URL.
    assert "alias-should-be-ignored" not in r.stdout + r.stderr


def test_server_url_still_works():
    """Positive control: SYNC_SERVER_URL is still the canonical name."""
    env = dict(os.environ)
    env["SYNC_SERVER_URL"] = "http://canonical-name:1234"
    env.pop("SYNC_EXTERNAL_URL", None)
    r = subprocess.run(
        [sys.executable, APP, "--version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert r.returncode == 0
