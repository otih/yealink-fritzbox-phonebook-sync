"""Regression test: the server must not leak its Python/stdlib version.

Every response on the error paths (404/401/403/429, via send_error and
send_response) carries a `Server:` header by default —
`BaseHTTP/0.6 Python/3.13.x` — handing an attacker the exact
interpreter version for free (version-specific exploits, recon).
The 200 path (`_serve`) never had the header; the error paths did.
The handler overrides `version_string()` to suppress it. Found during
the 2026-11-22 senior review; this test pins the fix on the live
server socket (not just the method's return value).
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


def _start_server() -> tuple[object, int]:
    srv = yfps._make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def _raw_get(port: int, path: str, extra_headers: bytes = b"") -> str:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(
        b"GET " + path.encode() + b" HTTP/1.1\r\nHost: 127.0.0.1\r\n" + extra_headers + b"\r\n"
    )
    chunks = []
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    s.close()
    return b"".join(chunks).decode("utf-8", errors="replace")


class TestNoServerVersionLeak:
    def test_404_path_has_no_python_version(self):
        srv, port = _start_server()
        try:
            resp = _raw_get(port, "/nonexistent")
            assert "Python/" not in resp, "Python version leaked on 404: %r" % resp[:200]
            assert "BaseHTTP" not in resp, "BaseHTTP version leaked on 404: %r" % resp[:200]
        finally:
            srv.shutdown()

    def test_401_path_has_no_python_version(self):
        srv, port = _start_server()
        try:
            # Auth enabled with wrong credentials → 401 via send_response
            yfps.auth_user = "admin"
            yfps.auth_pass = "secret"
            resp = _raw_get(
                port,
                "/menu.xml",
                b"Authorization: Basic dXNlcjpwdw==\r\n",  # user:pw (wrong)
            )
            assert "Python/" not in resp, "Python version leaked on 401: %r" % resp[:200]
            assert "BaseHTTP" not in resp, "BaseHTTP version leaked on 401: %r" % resp[:200]
        finally:
            yfps.auth_user = ""
            yfps.auth_pass = ""
            srv.shutdown()

    def test_health_path_has_no_python_version(self):
        srv, port = _start_server()
        try:
            resp = _raw_get(port, "/health")
            assert "Python/" not in resp, "Python version leaked on /health: %r" % resp[:200]
            assert "BaseHTTP" not in resp, "BaseHTTP version leaked on /health: %r" % resp[:200]
        finally:
            srv.shutdown()
