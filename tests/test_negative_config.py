"""Negative configuration tests — the fail-fast contract.

For EVERY env/flag variable: garbage input must abort startup with
exit code 1 AND a clear error naming the variable and the expected
format. A raw Python traceback that does not name the setting violates
the contract (the user cannot know WHAT to fix).

These tests run main() in a subprocess with a polluted environment —
no in-process monkeypatching, because the crash happens during argparse
construction (module import happens before main; env parsing too).
"""

import os
import subprocess
import sys

APP = os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")


def run_app(env_overrides):
    """Run the app with a polluted env; return (exit_code, combined_output)."""
    env = dict(os.environ)
    env.update(env_overrides)
    # --version needs no credentials; env parsing happens first
    proc = subprocess.run(
        [sys.executable, APP, "--version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout + proc.stderr


class TestNegativeEnvValues:
    """Garbage in every env variable → exit 1 + the variable named in
    the error (NOT a bare traceback)."""

    def test_fb_port_garbage(self):
        code, out = run_app({"FB_PORT": "abc"})
        assert code == 1
        assert "FB_PORT" in out, "error must name the variable, got: %s" % out[:200]

    def test_sync_listen_port_garbage(self):
        code, out = run_app({"SYNC_LISTEN_PORT": "xyz"})
        assert code == 1
        assert "SYNC_LISTEN_PORT" in out, "error must name the variable, got: %s" % out[:200]

    def test_sync_refresh_interval_garbage(self):
        code, out = run_app({"SYNC_REFRESH_INTERVAL": "kein-zahl"})
        assert code == 1
        assert "SYNC_REFRESH_INTERVAL" in out, "error must name the variable, got: %s" % out[:200]

    def test_fb_port_out_of_range(self):
        # Range validation lives in _validate_config, which runs on the
        # STARTUP path (not with --version, which exits in argparse).
        # Minimal valid credentials get us past the credential check to
        # the validator; FB_PORT=70000 must be rejected with the key named.
        env = {"FB_PORT": "70000", "FB_USER": "u", "FB_PASSWORD": "p"}
        full_env = dict(os.environ)
        full_env.update(env)
        proc = subprocess.run(
            [sys.executable, APP],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=30,
        )
        assert proc.returncode == 1
        out = proc.stdout + proc.stderr
        assert "fritzbox_port" in out or "FB_PORT" in out, out[:300]

    def test_sync_dedup_contacts_garbage(self):
        code, out = run_app({"SYNC_DEDUP_CONTACTS": "treu"})
        assert code == 1
        assert "SYNC_DEDUP_CONTACTS" in out

    def test_no_traceback_on_garbage(self):
        """A raw traceback means the error escaped argparse construction —
        the user sees Python internals instead of 'which variable is wrong'."""
        code, out = run_app({"FB_PORT": "abc"})
        assert code == 1
        assert "Traceback" not in out, "garbage env values must not crash with a traceback"


class TestValidEnvStillWorks:
    """Negative tests must not break the happy path: same variables with
    valid values still start (here: reach --version)."""

    def test_valid_values_pass(self):
        code, out = run_app(
            {
                "FB_PORT": "49000",
                "SYNC_LISTEN_PORT": "8080",
                "SYNC_REFRESH_INTERVAL": "3600",
                "SYNC_DEDUP_CONTACTS": "1",
            }
        )
        assert code == 0, out[:200]
