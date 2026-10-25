"""Tests for the HTTP handler: auth enforcement and URL routing.

Spins up the real HTTPServer on an ephemeral port and exercises it with
urllib — covers the 401/404/routing paths that the pure-function tests
cannot reach. No Fritzbox needed; the sync state is set directly.
"""

import base64
import importlib.util
import os
import threading
import urllib.error
import urllib.request

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


@pytest.fixture()
def server():
    """Start the real HTTP server on an ephemeral port; yield (base_url, state)."""
    srv = yfps._make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % port, yfps.state
    srv.shutdown()
    thread.join(timeout=5)


def _get(url, auth=None):
    """GET a URL; return (status, body). 4xx/5xx are returned, not raised."""
    req = urllib.request.Request(url)
    if auth:
        token = base64.b64encode(("%s:%s" % auth).encode()).decode()
        req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class TestHealthEndpoint:
    def test_health_open_without_auth(self, server):
        base, st = server
        yfps.auth_user = ""
        status, body = _get(base + "/health")
        assert status == 200
        assert '"status":"ok"' in body


class TestAuthEnforcement:
    @pytest.fixture(autouse=True)
    def enable_auth(self, server):
        base, st = server
        yfps.auth_user = "user1"
        yfps.auth_pass = "secret1"
        yield
        yfps.auth_user = ""
        yfps.auth_pass = ""

    def test_menu_rejected_without_auth(self, server):
        base, _ = server
        status, _body = _get(base + "/menu.xml")
        assert status == 401

    def test_menu_rejected_with_wrong_password(self, server):
        base, _ = server
        status, _body = _get(base + "/menu.xml", auth=("user1", "wrong"))
        assert status == 401

    def test_menu_rejected_with_wrong_user(self, server):
        base, _ = server
        status, _body = _get(base + "/menu.xml", auth=("other", "secret1"))
        assert status == 401

    def test_menu_accepted_with_correct_auth(self, server):
        base, _ = server
        status, body = _get(base + "/menu.xml", auth=("user1", "secret1"))
        assert status == 200
        # With empty sync state the menu falls back to a "not synced" body —
        # the contract here is 200 + the fallback marker, not the menu content.
        assert "Not synced yet" in body

    def test_contacts_accepted_with_correct_auth(self, server):
        base, _ = server
        with yfps.state.lock:
            yfps.state.contacts[7] = (
                '<?xml version="1.0" encoding="UTF-8"?>\n<YealinkIPPhoneDirectory>\n'
                "  <DirectoryEntry><Name>X</Name>"
                "<Telephone>123</Telephone></DirectoryEntry>\n"
                "</YealinkIPPhoneDirectory>"
            )
        status, body = _get(base + "/contacts/7.xml", auth=("user1", "secret1"))
        assert status == 200
        assert "<DirectoryEntry><Name>X</Name>" in body

    def test_malformed_auth_header_rejected(self, server):
        base, _ = server
        req = urllib.request.Request(base + "/menu.xml")
        req.add_header("Authorization", "Basic !!!not-base64!!!")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 401


class TestRouting:
    @pytest.fixture(autouse=True)
    def disable_auth(self, server):
        yfps.auth_user = ""
        yield

    def test_root_serves_menu(self, server):
        base, _ = server
        status, body = _get(base + "/")
        assert status == 200

    def test_contacts_with_numeric_id(self, server):
        base, _ = server
        status, _body = _get(base + "/contacts/1.xml")
        assert status == 200

    def test_contacts_with_non_numeric_id_is_404(self, server):
        base, _ = server
        status, _body = _get(base + "/contacts/abc.xml")
        assert status == 404

    def test_unknown_path_is_404(self, server):
        base, _ = server
        status, _body = _get(base + "/does-not-exist")
        assert status == 404

    def test_metrics_open_without_auth(self, server):
        base, _ = server
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_sync_success_total" in body
        assert "# TYPE yfps_sync_success_total counter" in body
