"""Tests for the HTTP handler: auth enforcement and URL routing.

Spins up the real HTTPServer on an ephemeral port and exercises it with
urllib — covers the 401/404/routing paths that the pure-function tests
cannot reach. No Fritzbox needed; the sync state is set directly.
"""

import base64
import importlib.util
import os
import threading
import time
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
    """Start the real HTTP server on an ephemeral port; yield (base_url, state).

    The server shares the module-global state across tests — reset the
    per-process counters so each test starts from a known point.
    """
    with yfps.state.lock:
        yfps.state.phone_fetches = 0
        yfps.state.last_phone_fetch = 0
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
        base, _st = server
        yfps.auth_user = ""
        status, body = _get(base + "/health")
        assert status == 200
        assert '"status":"ok"' in body

    def test_health_stays_ok_when_sync_never_ran(self, server):
        """Docker/K8s restart semantics: /health must stay 200 + ok even when
        the Fritzbox was never reachable — the server is healthy, only the
        upstream sync is not. Degradation is reported via /metrics only."""
        base, st = server
        yfps.auth_user = ""
        with st.lock:
            st.last_sync = 0  # never synced
        status, body = _get(base + "/health")
        assert status == 200
        assert '"status":"ok"' in body


class TestAuthEnforcement:
    @pytest.fixture(autouse=True)
    def enable_auth(self, server):
        _base, _st = server
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

    def test_auth_failures_counted_in_metrics(self, server):
        """A rejected Basic-Auth attempt must show up in yfps_auth_failures_total."""
        base, _ = server
        with yfps.state.lock:
            yfps.state.auth_failures = 0
        status, _ = _get(base + "/menu.xml", auth=("user1", "wrong"))
        assert status == 401
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_auth_failures_total 1" in body
        assert "# TYPE yfps_auth_failures_total counter" in body

    def test_rate_limit_rejections_counted_in_metrics(self, server):
        """Requests blocked with 429 must show up in yfps_auth_rate_limited_total."""
        base, _ = server
        with yfps.state.lock:
            yfps.state.auth_failures = 0
            yfps.state.auth_rate_limited = 0
        # Fresh limiter: module-global state may carry failures from
        # earlier tests in this class.
        yfps.rate_limiter = yfps._RateLimiter()
        # Exhaust the per-IP limit (5 failures within 60s) → then 429
        statuses = [_get(base + "/menu.xml", auth=("user1", "wrong"))[0] for _ in range(7)]
        assert statuses == [401, 401, 401, 401, 401, 429, 429]
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_auth_rate_limited_total 2" in body
        assert "# TYPE yfps_auth_rate_limited_total counter" in body


class TestDegradedMetric:
    """yfps_degraded: 1 when the last successful sync is older than 3x the
    refresh interval (or never synced), 0 otherwise. /health stays 200/ok
    in both states — restart semantics must not change."""

    def test_degraded_zero_when_sync_fresh(self, server):
        base, st = server
        with st.lock:
            st.last_sync = time.time()
            st.refresh_interval = 3600
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_degraded 0" in body

    def test_degraded_one_when_sync_never_ran(self, server):
        base, st = server
        with st.lock:
            st.last_sync = 0
            st.refresh_interval = 3600
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_degraded 1" in body

    def test_degraded_one_when_sync_stale(self, server):
        base, st = server
        with st.lock:
            st.refresh_interval = 3600
            st.last_sync = time.time() - 4 * 3600  # older than 3x interval
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_degraded 1" in body

    def test_degraded_boundary_exactly_3x_interval_is_ok(self, server):
        base, st = server
        with st.lock:
            st.refresh_interval = 3600
            st.last_sync = time.time() - 3 * 3600  # exactly 3x → not degraded
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_degraded 0" in body


class TestRouting:
    @pytest.fixture(autouse=True)
    def disable_auth(self, server):
        yfps.auth_user = ""
        yield

    def test_root_serves_menu(self, server):
        base, _ = server
        status, _body = _get(base + "/")
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

    def test_metrics_exposes_build_info(self, server):
        base, _ = server
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "# TYPE yfps_build_info gauge" in body
        assert 'yfps_build_info{version="%s"} 1' % yfps.APP_VERSION in body

    def test_metrics_expose_phonebook_fetch_tracking(self, server):
        """Fetching /menu.xml must be reflected in the fetch metrics."""
        base, _ = server
        # Before any phonebook fetch: never fetched (-1 / 0)
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_phonebook_fetch_total 0" in body
        assert "yfps_phonebook_fetch_age_seconds -1" in body

        # Fetch the menu like a phone would
        _get(base + "/menu.xml")

        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_phonebook_fetch_total 1" in body
        total_line = next(
            ln
            for ln in body.splitlines()
            if ln.startswith("yfps_phonebook_fetch_last_timestamp_seconds")
        )
        assert int(total_line.split()[-1]) > 0
        age_line = next(
            ln for ln in body.splitlines() if ln.startswith("yfps_phonebook_fetch_age_seconds")
        )
        assert int(age_line.split()[-1]) == 0  # just fetched


class TestPerPhonebookMetrics:
    """yfps_phonebook_contacts{id=..., name=...}: contact count per
    phonebook — a shrinking source (e.g. broken Google import into the
    Fritzbox) becomes visible per phonebook, not just in the global sum."""

    def test_per_phonebook_gauge_emitted(self, server):
        base, st = server
        with st.lock:
            st.pb_meta = [
                {"id": 1, "name": "Work", "count": 193},
                {"id": 2, "name": "Privat", "count": 42},
            ]
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "# TYPE yfps_phonebook_contacts gauge" in body
        assert 'yfps_phonebook_contacts{id="1",name="Work"} 193' in body
        assert 'yfps_phonebook_contacts{id="2",name="Privat"} 42' in body

    def test_empty_state_emits_no_gauge_lines(self, server):
        base, st = server
        with st.lock:
            st.pb_meta = []
        status, body = _get(base + "/metrics")
        assert status == 200
        assert "yfps_phonebook_contacts{" not in body

    def test_phonebook_name_escaped_in_label(self, server):
        base, st = server
        with st.lock:
            st.pb_meta = [{"id": 3, "name": 'Book "quoted" \\ slash', "count": 1}]
        status, body = _get(base + "/metrics")
        assert status == 200
        # Backslash and quote must be escaped per Prometheus label rules
        assert 'yfps_phonebook_contacts{id="3",name="Book \\"quoted\\" \\\\ slash"} 1' in body


class TestPerIpFetchMetrics:
    """yfps_phonebook_fetch_age_seconds_by_ip{ip=...}: one line per
    fetching client IP — WHICH phone last pulled its phonebook (multi-
    handset setups), not just that some phone did. Bounded: only the 10
    most recently seen IPs are kept (cardinality safety)."""

    def test_fetch_records_client_ip(self, server):
        base, _ = server
        with yfps.state.lock:
            yfps.state.phone_fetch_ips = {}
            yfps.state.last_phone_fetch = 0
        _get(base + "/menu.xml")
        status, body = _get(base + "/metrics")
        assert status == 200
        assert 'yfps_phonebook_fetch_age_seconds_by_ip{ip="127.0.0.1"}' in body

    def test_labeled_ip_matches_client(self, server):
        base, _ = server
        with yfps.state.lock:
            yfps.state.phone_fetch_ips = {}
            yfps.state.last_phone_fetch = 0
        _get(base + "/menu.xml")
        _status, body = _get(base + "/metrics")
        assert 'yfps_phonebook_fetch_age_seconds_by_ip{ip="127.0.0.1"} 0' in body

    def test_per_ip_map_bounded_to_10(self, server):
        base, _ = server
        # Fresh limiter: earlier suite tests exhaust the per-IP budget
        # (module-global state) — the fetch here must actually happen.
        yfps.rate_limiter = yfps._RateLimiter()
        yfps.auth_user = ""
        # 15 different fake IPs recorded; one more fetch triggers the
        # bound — the map must stay <= 10 entries
        with yfps.state.lock:
            yfps.state.phone_fetch_ips = {"10.0.0.%d" % i: 1700000000.0 + i for i in range(15)}
        _get(base + "/menu.xml")  # records 127.0.0.1 -> bound applies
        with yfps.state.lock:
            assert len(yfps.state.phone_fetch_ips) <= 10


class TestAllXmlEndpoint:
    """/all.xml: combined flat directory for single-slot phones.
    Positive: merges + serves. Negative: auth-protected like every
    phonebook endpoint, counts as a phone fetch."""

    def test_all_xml_served_without_auth_when_auth_disabled(self, server):
        base, _ = server
        yfps.auth_user = ""
        with yfps.state.lock:
            yfps.state.contacts[3] = (
                '<?xml version="1.0" encoding="UTF-8"?>\n<YealinkIPPhoneDirectory>\n'
                "  <DirectoryEntry><Name>X</Name><Telephone>1</Telephone></DirectoryEntry>\n"
                "</YealinkIPPhoneDirectory>"
            )
        status, body = _get(base + "/all.xml")
        assert status == 200
        assert "<Name>X</Name>" in body
        assert body.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_all_xml_rejected_without_auth(self, server):
        base, _ = server
        # Fresh limiter: earlier suite tests may have exhausted the
        # per-IP budget (module-global state) — we assert 401, not 429.
        yfps.rate_limiter = yfps._RateLimiter()
        yfps.auth_user = "u"
        yfps.auth_pass = "p"
        status, _ = _get(base + "/all.xml")
        assert status == 401
        yfps.auth_user = ""
        yfps.auth_pass = ""

    def test_all_xml_empty_state_serves_empty_directory(self, server):
        base, _ = server
        yfps.auth_user = ""
        with yfps.state.lock:
            yfps.state.contacts = {}
        status, body = _get(base + "/all.xml")
        assert status == 200
        assert "<DirectoryEntry>" not in body
        assert "<YealinkIPPhoneDirectory>" in body


class TestFetchIpBoundDeterministic:
    """The bound is enforced defensively by the /metrics emitter —
    no fetch required. This closes the race the old test only worked
    around with a fresh rate limiter."""

    def test_metrics_emitter_prunes_inflated_map(self, server):
        base, _ = server
        # Inflate WITHOUT any fetch — the emitter must prune to 10
        with yfps.state.lock:
            yfps.state.phone_fetch_ips = {"10.0.0.%d" % i: 1700000000.0 + i for i in range(15)}
        status, body = _get(base + "/metrics")
        assert status == 200
        # 15 entries -> 10 lines max in the per-IP metric family
        ip_lines = [
            ln
            for ln in body.splitlines()
            if ln.startswith("yfps_phonebook_fetch_age_seconds_by_ip{")
        ]
        assert len(ip_lines) == 10
