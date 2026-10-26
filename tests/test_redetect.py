"""Tests for periodic phonebook-ID re-detection in the sync loop.

When FB_PHONEBOOK_ID is unset (auto-detect), ONE running sync_loop must
re-fetch the phonebook ID list on every cycle — a phonebook created on
the Fritzbox at runtime appears on the phone without a restart. With an
explicitly configured ID list, the list is used verbatim forever.
"""

import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


class _StopLoop(Exception):
    """Raised by the patched sleep to end the loop after N cycles."""


class ReDetectClient:
    """Fritzbox stand-in whose ID list can grow between calls."""

    def __init__(self, ids):
        self.ids = list(ids)
        self.id_calls = 0

    def get_phonebook_ids(self):
        self.id_calls += 1
        return list(self.ids)

    def fetch_phonebook(self, pid):
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<phonebooks><phonebook owner="0" name="PB%d">'
            b"<contact><person><realName>C%d</realName></person>"
            b'<telephony><number type="mobile">+49 170 %d</number></telephony></contact>'
            b"</phonebook></phonebooks>" % (pid, pid, pid)
        )


def _reset_state():
    with yfps.state.lock:
        yfps.state.contacts = {}
        yfps.state.pb_meta = []


class TestPeriodicRedetection:
    def test_new_phonebook_appears_within_running_loop(self):
        # ONE loop run, TWO cycles. The Fritzbox grows between cycles.
        _reset_state()
        client = ReDetectClient([0])
        real_sleep = yfps.time.sleep
        seen = {"n": 0}

        def _sleep(secs):
            seen["n"] += 1
            if seen["n"] >= 2:
                raise _StopLoop()
            client.ids = [0, 5]  # phonebook 5 created after cycle 1

        yfps.time.sleep = _sleep
        try:
            yfps.sync_loop(client, [], "http://x", "http://x", 0)
        except _StopLoop:
            pass
        finally:
            yfps.time.sleep = real_sleep
        assert client.id_calls == 2
        assert {m["id"] for m in yfps.state.pb_meta} == {0, 5}

    def test_single_loop_run_detects_growth_across_cycles(self):
        # Stronger: one continuous loop, cycle 1 sees [0], cycle 2 sees [0,5]
        _reset_state()
        client = ReDetectClient([0])
        real_sleep = yfps.time.sleep
        seen_ids = []

        def _sleep(secs):
            seen_ids.append(sorted(m["id"] for m in yfps.state.pb_meta))
            if len(seen_ids) >= 2:
                raise _StopLoop()
            client.ids = [0, 5]  # Fritzbox gains a phonebook after cycle 1

        yfps.time.sleep = _sleep
        try:
            yfps.sync_loop(client, [], "http://x", "http://x", 0)
        except _StopLoop:
            pass
        finally:
            yfps.time.sleep = real_sleep
        assert seen_ids[0] == [0]
        assert seen_ids[1] == [0, 5], "cycle 2 must include the new phonebook 5"
        assert client.id_calls == 2

    def test_explicit_ids_never_redetected(self):
        # Explicit list [7]: no detection calls ever, even across cycles
        _reset_state()
        client = ReDetectClient([0, 1, 2])  # would be detected — must NOT be used
        real_sleep = yfps.time.sleep
        calls = {"n": 0}

        def _sleep(secs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise _StopLoop()

        yfps.time.sleep = _sleep
        try:
            yfps.sync_loop(client, [7], "http://x", "http://x", 0)
        except _StopLoop:
            pass
        finally:
            yfps.time.sleep = real_sleep
        assert client.id_calls == 0
        assert {m["id"] for m in yfps.state.pb_meta} == {7}
