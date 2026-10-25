"""Concurrency tests: the server must serve requests in parallel.

Regression guard for the 24/7 requirement: a single slow/hung client
must never block other requests (health checks, phone polls).
"""

import importlib.util
import os
import socket
import threading
import urllib.request

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


@pytest.fixture()
def server():
    srv = yfps._make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % port
    srv.shutdown()
    thread.join(timeout=5)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status


def test_concurrent_requests_all_served(server):
    """20 parallel requests must all complete while one client holds a
    connection open without reading (simulates a hung phone)."""
    base = server
    port = int(base.rsplit(":", 1)[1])
    # A client that connects and never sends a request: occupies the socket.
    hung = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        results = []
        errors = []

        def worker():
            try:
                results.append(_get(base + "/health"))
            except Exception as exc:  # pragma: no cover - only on failure
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors, "requests failed under concurrency: %r" % errors
        assert results == [200] * len(results)
    finally:
        hung.close()


def test_server_type_is_threading():
    """The server class must be ThreadingHTTPServer (24/7 requirement:
    one hung client must not block the health check)."""
    assert yfps._SERVER_CLASS is yfps.ThreadingHTTPServer
