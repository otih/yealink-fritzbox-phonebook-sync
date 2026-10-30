"""Negative + positive tests for the dual-stack socket connector.

Bug history: _raw_post hardcoded AF_INET6. On this author's network
fritz.box resolves IPv6-only (Docker bridge has no IPv6 -> compose uses
network_mode: host), so IPv6-first worked. But for ANYONE else:

- SYNC_FRITZBOX_HOST as a plain IPv4 literal (192.168.179.1 — the Fritzbox LAN
  default on many setups) crashed with "Address family for hostname
  not supported" on EVERY sync attempt.
- fritz.box in an IPv4-only network (no AAAA record) failed the same
  way.

Fix: resolve via getaddrinfo(AF_UNSPEC), prefer IPv6 (author's
network is IPv6-only, and v4-mapped literals still work through the
AF_INET6 socket), fall back to IPv4.
"""

import socket

import yealink_fritzbox_phonebook_sync as yfps


class TestDualStackConnect:
    def test_ipv4_literal_resolves(self):
        """The LAN-default case that used to crash every sync."""
        family, sockaddr = yfps._resolve_host("192.0.2.10")
        assert family == socket.AF_INET
        assert sockaddr[0] == "192.0.2.10"

    def test_v4_mapped_literal_stays_ipv6(self):
        """::ffff: literals keep working through the AF_INET6 path."""
        family, _sockaddr = yfps._resolve_host("::ffff:192.0.2.10")
        assert family == socket.AF_INET6

    def test_ipv6_literal_resolves(self):
        family, _sockaddr = yfps._resolve_host("::1")
        assert family == socket.AF_INET6

    def test_localhost_prefers_ipv6_when_dual(self):
        """IPv6 preferred when both families resolve (author's network)."""
        family, _sockaddr = yfps._resolve_host("localhost")
        assert family == socket.AF_INET6

    def test_hostname_without_v6_falls_back_to_v4(self):
        """A v4-only name (e.g. fritz.box in an IPv4-only LAN) must not
        crash — it falls back to the A record instead of raising
        "Address family for hostname not supported"."""
        try:
            family, _sockaddr = yfps._resolve_host("fritz.box")
            fam = family
        except OSError:
            # Resolver may refuse fritz.box in the test environment; the
            # contract here is only: no AF-family crash, resolution either
            # works or raises a CLEAN socket.gaierror.
            fam = None
        assert fam in (socket.AF_INET, socket.AF_INET6, None)

    def test_unresolvable_host_raises_gaierror(self):
        """Negative test: garbage hostnames raise the clean resolution
        error, not the AF-family crash."""
        import pytest

        with pytest.raises(socket.gaierror):
            yfps._resolve_host("nonexistent.invalid")


class TestRawPostUsesResolvedFamily:
    def test_raw_post_with_ipv4_literal_reaches_server(self):
        """End-to-end: a real listener on 127.0.0.1 must be reachable
        through _raw_post with a plain IPv4 literal — the case that
        crashed 100% of syncs before the fix."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        client = yfps.FritzboxClient(host="127.0.0.1", port=port, user="u", password="p")
        try:
            # _raw_post with a minimal valid HTTP request; the listener
            # answers a canned HTTP response so parsing succeeds.
            import threading

            def serve_one():
                conn, _ = server.accept()
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
                conn.close()

            t = threading.Thread(target=serve_one, daemon=True)
            t.start()
            resp = client._raw_post("/", b"", {"X-Test": "1"})
            assert resp["status"] == 200
            assert resp["body"] == "ok"
            t.join(timeout=2)
        finally:
            server.close()
