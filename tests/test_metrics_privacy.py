"""Regression test: /metrics must not expose phonebook names.

The /metrics endpoint is deliberately auth-free (operational counters,
Prometheus scrape convenience). The threat model justifies this with
"no contact data" — but the yfps_phonebook_contacts metric carried the
phonebook NAME as a label: `yfps_phonebook_contacts{id="0",
name="Familie Mueller"} 42`. Phonebook names are private metadata
(household structure, family names); any LAN device could read them
without credentials — contradicting the model's own promise. Found
during the 2026-11-22 red-team audit.

The fix drops the name label; the id label remains (the id→name mapping
lives in the auth-protected /menu.xml). This test pins: no `name=` label
in ANY yfps_phonebook_contacts line, the id label preserved, and the
metric still reporting the counts.
"""

import importlib.util
import os
import socket
import threading

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)

PRIVATE_NAME = "Familie Müller"


def _get_metrics() -> str:
    srv = yfps._make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
        s.sendall(b"GET /metrics HTTP/1.1\r\nHost: x\r\n\r\n")
        # Read to EOF: the server sends Connection: close, and header +
        # body can arrive in separate TCP segments — stopping at the
        # first \r\n\r\n would randomly truncate the body (metric lines).
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        return data.decode("utf-8", errors="replace")
    finally:
        srv.shutdown()


class TestMetricsNoPhonebookNames:
    def test_phonebook_name_not_in_metrics(self):
        # Simulate a synced phonebook with a private name
        yfps.state.pb_meta = [{"id": 0, "name": PRIVATE_NAME, "count": 42}]
        try:
            metrics = _get_metrics()
        finally:
            yfps.state.pb_meta = []
        # The private name must NOT appear anywhere in the auth-free output
        assert PRIVATE_NAME not in metrics, "phonebook name leaked into auth-free /metrics: %r" % [
            ln for ln in metrics.splitlines() if PRIVATE_NAME in ln
        ]

    def test_phonebook_contacts_metric_keeps_id_and_count(self):
        # The metric itself stays useful for monitoring: per-book contact
        # counts by ID (the id→name mapping lives in the auth-protected
        # /menu.xml — an operator can join there when needed).
        yfps.state.pb_meta = [{"id": 0, "name": PRIVATE_NAME, "count": 42}]
        try:
            metrics = _get_metrics()
        finally:
            yfps.state.pb_meta = []
        contact_lines = [
            ln for ln in metrics.splitlines() if ln.startswith("yfps_phonebook_contacts{")
        ]
        assert contact_lines, "yfps_phonebook_contacts metric missing entirely"
        for ln in contact_lines:
            assert 'id="0"' in ln, "id label lost: %r" % ln
            assert ln.rstrip().endswith(" 42"), "count value lost: %r" % ln
            # No name label on any contact line — id only
            assert "name=" not in ln, "name label still present: %r" % ln
