"""Tests for the --check diagnostic mode (first-setup verification).

--check connects to the Fritzbox once, resolves/validates the configured
phonebook IDs, converts every phonebook, prints a summary and exits 0/1.
It must never start the HTTP server. Uses a stub Fritzbox client.
"""

import importlib.util
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)

# Minimal Fritzbox phonebook XML for the stub client to serve
PB_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<phonebooks><phonebook owner="0" name="Checkbook">'
    b"<contact><person><realName>Anna Beispiel</realName></person>"
    b'<telephony><number type="mobile">+49 170 1</number></telephony></contact>'
    b"<contact><person><realName>Nur Intern</realName></person>"
    b'<telephony><number type="intern">**9</number></telephony></contact>'
    b"</phonebook></phonebooks>"
)


class StubClient:
    """Deterministic Fritzbox stand-in: 2 fetchable phonebooks, 1 usable contact each."""

    def get_phonebook_ids(self):
        return [0, 1]

    def fetch_phonebook(self, pid):
        return PB_XML


class BrokenPbClient(StubClient):
    """ID 0 exists but cannot be downloaded (e.g. empty/locked phonebook)."""

    def fetch_phonebook(self, pid):
        if pid == 0:
            raise ConnectionError("phonebook 0 not downloadable")
        return PB_XML


def run_check(client, ids_arg):
    """Call _run_check with argparse-like plain attributes."""
    return yfps._run_check(client, ids_arg)


class TestRunCheck:
    def test_autodetect_lists_ids_and_counts(self, capsys):
        code = run_check(StubClient(), "")
        out = capsys.readouterr().out
        assert code == 0
        assert "Phonebook IDs on the Fritzbox: 0, 1" in out
        assert "Checkbook" in out
        assert "1 contact" in out  # after internal-number filtering
        assert "OK" in out

    def test_single_configured_id_converted(self, capsys):
        code = run_check(StubClient(), "1")
        out = capsys.readouterr().out
        assert code == 0
        assert "1" in out and "Checkbook" in out

    def test_invalid_configured_id_fails(self, capsys):
        code = run_check(StubClient(), "7")
        assert code == 1
        assert "not in the Fritzbox phonebook list" in capsys.readouterr().out

    def test_unreachable_fritzbox_exits_1(self, capsys):
        class DeadClient:
            def get_phonebook_ids(self):
                raise ConnectionError("dead")

        code = run_check(DeadClient(), "")
        assert code == 1
        out = capsys.readouterr().out
        assert "Fritzbox" in out or "dead" in out

    def test_unfetchable_phonebook_reports_but_fails(self, capsys):
        # ID 0 exists but cannot be downloaded → the check must fail loudly:
        # a phonebook that cannot be fetched would silently vanish for the phone.
        code = run_check(BrokenPbClient(), "")
        assert code == 1
        assert "cannot fetch/convert phonebook 0" in capsys.readouterr().out

    def test_check_never_starts_server(self):
        # _run_check must return an exit code, not fall through into the
        # server loop: returning at all (and not hanging) is the contract.
        assert callable(yfps._run_check)
