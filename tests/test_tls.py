"""Tests for optional TLS (SYNC_TLS_CERT / SYNC_TLS_KEY).

Contract: TLS is strictly opt-in — unset (default) means plain HTTP,
untouched behavior. When both cert and key are set the server wraps its
socket in TLS. Negative contract per the fail-fast convention: one of
cert/key without the other, or unreadable files → startup abort with a
clear error naming the setting. Trust management is documented as the
OPERATOR's responsibility (public cert or CA rollout on the phone) —
not this tool's.
"""

import importlib.util
import os
import ssl
import threading
import urllib.request

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


@pytest.fixture()
def tls_pair(tmp_path):
    """Generate a self-signed cert/key pair via the ssl/openssl stdlib path."""
    import subprocess

    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "2",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return str(cert), str(key)


def _start_server(cert, key, port):
    """Start a TLS (or plain) server on an ephemeral port; return (port, srv)."""
    srv = yfps._make_server("127.0.0.1", port, tls_cert=cert, tls_key=key)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv


class TestTlsServer:
    def test_tls_serves_https(self, tls_pair):
        cert, key = tls_pair
        srv = _start_server(cert, key, 0)
        port = srv.server_address[1]
        try:
            # Unverified context on purpose: we assert TLS wrapping works,
            # not trust (the phone-side trust story is documented).
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(
                "https://127.0.0.1:%d/health" % port, context=ctx, timeout=5
            ) as resp:
                body = resp.read().decode()
            assert '"status":"ok"' in body
        finally:
            srv.shutdown()

    def test_plain_mode_untouched_when_unset(self):
        # No cert/key -> plain HTTP server, byte-identical behavior
        srv = yfps._make_server("127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=5) as resp:
                assert '"status":"ok"' in resp.read().decode()
        finally:
            srv.shutdown()

    def test_http_request_to_tls_port_fails(self, tls_pair):
        # Negative: plain HTTP against the TLS port must NOT answer a
        # valid response (the socket speaks TLS now)
        cert, key = tls_pair
        srv = _start_server(cert, key, 0)
        port = srv.server_address[1]
        try:
            with pytest.raises((urllib.request.URLError, ConnectionError)):
                urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=5)
        finally:
            srv.shutdown()


class TestTlsConfigValidation:
    def test_cert_without_key_aborts(self, tls_pair, monkeypatch):
        cert, _key = tls_pair
        env = {"SYNC_TLS_CERT": cert}
        monkeypatch.setattr(os, "getenv", lambda name, default=None: env.get(name, default))
        with pytest.raises(ValueError, match="SYNC_TLS_KEY"):
            yfps._load_tls_config()

    def test_key_without_cert_aborts(self, tls_pair, monkeypatch):
        _cert, key = tls_pair
        env = {"SYNC_TLS_KEY": key}
        monkeypatch.setattr(os, "getenv", lambda name, default=None: env.get(name, default))
        with pytest.raises(ValueError, match="SYNC_TLS_CERT"):
            yfps._load_tls_config()

    def test_missing_cert_file_aborts(self, monkeypatch):
        env = {"SYNC_TLS_CERT": "/nonexistent/cert.pem", "SYNC_TLS_KEY": "/nonexistent/key.pem"}
        monkeypatch.setattr(os, "getenv", lambda name, default=None: env.get(name, default))
        with pytest.raises(ValueError, match="SYNC_TLS_CERT"):
            yfps._load_tls_config()

    def test_both_unset_returns_none(self, monkeypatch):
        monkeypatch.setattr(os, "getenv", lambda name, default=None: default)
        assert yfps._load_tls_config() is None


class TestTlsHardening:
    """SSL-Labs-style hardening: TLS 1.2 minimum, ECDHE+AEAD-only
    (GCM/CHACHA20, no CBC, no static-RSA suites), HSTS header on TLS."""

    def _tls_server(self, tls_pair):
        cert, key = tls_pair
        srv = yfps._make_server("127.0.0.1", 0, tls_cert=cert, tls_key=key)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        return srv

    def test_minimum_version_is_tls12(self, tls_pair):
        import socket as _socket

        srv = self._tls_server(tls_pair)
        port = srv.server_address[1]
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            ctx.maximum_version = ssl.TLSVersion.TLSv1_1
            with pytest.raises(ssl.SSLError):
                with _socket.create_connection(("127.0.0.1", port), timeout=3) as raw:
                    with ctx.wrap_socket(raw):
                        pass
        finally:
            srv.shutdown()

    def test_only_ecdhe_aead_suites(self, tls_pair):
        import socket as _socket

        srv = self._tls_server(tls_pair)
        port = srv.server_address[1]
        try:
            for suite in ("AES128-GCM-SHA256", "AES256-SHA", "ECDHE-RSA-AES128-SHA"):
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ctx.maximum_version = ssl.TLSVersion.TLSv1_2
                ctx.set_ciphers(suite)
                with pytest.raises(ssl.SSLError):
                    with _socket.create_connection(("127.0.0.1", port), timeout=3) as raw:
                        with ctx.wrap_socket(raw):
                            pass
        finally:
            srv.shutdown()

    def test_hsts_header_on_tls_responses(self, tls_pair):
        import urllib.request

        srv = self._tls_server(tls_pair)
        port = srv.server_address[1]
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(
                "https://127.0.0.1:%d/health" % port, context=ctx, timeout=5
            ) as resp:
                assert resp.headers.get("Strict-Transport-Security") == (
                    "max-age=31536000; includeSubDomains"
                )
        finally:
            srv.shutdown()

    def test_no_hsts_on_plain_http(self):
        import urllib.request

        srv = yfps._make_server("127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=5) as resp:
                assert resp.headers.get("Strict-Transport-Security") is None
        finally:
            srv.shutdown()
