"""Tests for FritzboxClient — the SOAP/Digest path, with a mock socket.

The raw-socket SOAP path is the least-covered block of the codebase
(~36% total coverage gap). This suite pins the behaviors that matter
operationally: digest computation against the RFC 7616 rules, the
challenge-retry loop (the Fritzbox answers 401 OR 500 inconsistently),
the no-auth fallback, and the phonebook-ID parsing. The mock replaces
socket.socket so no real Fritzbox is needed.
"""

import hashlib
import importlib.util
import os
import re
from unittest.mock import patch

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)

CHALLENGE = 'Digest realm=" FritzBox! ", nonce="ABC123", algorithm=MD5, qop="auth"'


def _http_response(status, headers=None, body=b""):
    headers = headers or {}
    lines = [f"HTTP/1.1 {status} X\r\n"]
    for k, v in headers.items():
        lines.append(f"{k}: {v}\r\n")
    lines.append(f"Content-Length: {len(body)}\r\n\r\n")
    return ("".join(lines)).encode() + body


def _client():
    return yfps.FritzboxClient("fritz.box", 49000, "user1", "secret1")


class MockSocket:
    """Scripted socket for _raw_post: ONE response per socket, then EOF.

    _raw_post does one request per socket (Connection: close) and reads
    to EOF — so a socket serves exactly one canned HTTP response.
    """

    def __init__(self, response):
        self.response = response
        self._served = False
        self.sent = []

    def connect(self, addr):
        pass

    def settimeout(self, t):
        pass

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, n):
        if not self._served:
            self._served = True
            return self.response
        return b""

    def close(self):
        pass


def _patch_socket(responses):
    """Patch socket.socket: sequential sockets serve the scripted responses.

    Returns (sent_list, ctx) — sent_list collects every request payload
    across all sockets this test creates.
    """
    queue = list(responses)
    sent = []

    class _ScriptedSocket(MockSocket):
        def __init__(self, *args, **kwargs):
            super().__init__(queue.pop(0) if queue else b"")

        def sendall(self, data):
            sent.append(data)
            super().sendall(data)

    ctx = patch.object(yfps.socket, "socket", _ScriptedSocket)
    return sent, ctx


class TestBuildDigestAuth:
    def test_digest_computation_rfc7616_qop(self):
        """The qop-variant response must be the RFC 7616 MD5 composition."""
        c = _client()
        hdr = c._build_digest_auth(CHALLENGE, "/upnp/control/x_contact")
        cnonce = re.search(r'cnonce="([^"]+)"', hdr).group(1)
        nc = "00000001"
        ha1 = hashlib.md5(b"user1: FritzBox! :secret1").hexdigest()
        ha2 = hashlib.md5(b"POST:/upnp/control/x_contact").hexdigest()
        expected = hashlib.md5(f"{ha1}:ABC123:{nc}:{cnonce}:auth:{ha2}".encode()).hexdigest()
        assert f'response="{expected}"' in hdr

    def test_digest_without_qop(self):
        c = _client()
        challenge = 'Digest realm="FritzBox", nonce="N1"'
        hdr = c._build_digest_auth(challenge, "/uri")
        ha1 = hashlib.md5(b"user1:FritzBox:secret1").hexdigest()
        ha2 = hashlib.md5(b"POST:/uri").hexdigest()
        expected = hashlib.md5(f"{ha1}:N1:{ha2}".encode()).hexdigest()
        assert f'response="{expected}"' in hdr
        assert "qop" not in hdr

    def test_malformed_challenge_raises(self):
        c = _client()
        with pytest.raises(ValueError, match="Malformed digest challenge"):
            c._build_digest_auth("Bearer something-else", "/uri")


class TestSoapFlow:
    def test_soap_with_digest_challenge(self):
        """401 with challenge -> digest auth -> 200 with the SOAP body."""
        c = _client()
        responses = [
            _http_response(401, {"WWW-Authenticate": CHALLENGE}, b"Unauthorized"),
            _http_response(200, {}, b"<result>phonebooks</result>"),
        ]
        sent, ctx = _patch_socket(responses)
        with ctx, patch.object(yfps.time, "sleep", lambda s: None):
            out = c._soap("GetPhonebookList")
        assert "phonebooks" in out
        assert b"Authorization: Digest" in sent[1]

    def test_soap_retries_until_challenge(self):
        """Fritzbox quirk: 500 SOAP fault on the first attempts, then 401."""
        c = _client()
        responses = [
            _http_response(500, {}, b"SOAP fault"),  # no challenge
            _http_response(500, {}, b"SOAP fault"),  # no challenge
            _http_response(401, {"WWW-Authenticate": CHALLENGE}, b""),
            _http_response(200, {}, b"<list>0,1</list>"),
        ]
        sent, ctx = _patch_socket(responses)
        with ctx, patch.object(yfps.time, "sleep", lambda s: None):
            out = c._soap("GetPhonebookList")
        assert "<list>0,1</list>" in out
        assert len(sent) == 4  # 3 challenge attempts + 1 authed

    def test_soap_persistent_failure_raises(self):
        """Every attempt fails at the socket level (OSError) -> RuntimeError
        with the last exception, after MAX_CHALLENGE_RETRIES tries."""
        c = _client()

        class _DeadSocket(MockSocket):
            def __init__(self, *args, **kwargs):
                super().__init__(b"")

            def connect(self, addr):
                raise OSError("network unreachable")

        with patch.object(yfps.socket, "socket", _DeadSocket), patch.object(
            yfps.time, "sleep", lambda s: None
        ):
            with pytest.raises(RuntimeError, match="could not obtain digest challenge"):
                c._soap("GetPhonebookList")

    def test_soap_500_without_challenge_falls_into_noauth_path(self):
        """500 SOAP faults WITHOUT a challenge header are not retried as
        errors — the loop discards them (auth_hdr stays empty, no
        exception), and the LAST response body is returned by the
        no-auth fallback. Documented quirk: the 'sometimes 500 instead
        of 401' Fritzbox behavior only works because a 500 body carrying
        no challenge ends up HERE, and real Fritzboxes eventually answer
        401 on a retry. The caller sees the 500 body as if unauthenticated."""
        c = _client()
        responses = [_http_response(500, {}, b"SOAP fault")] * yfps.MAX_CHALLENGE_RETRIES
        sent, ctx = _patch_socket(responses)
        with ctx, patch.object(yfps.time, "sleep", lambda s: None):
            out = c._soap("GetPhonebookList")
        assert "SOAP fault" in out

    def test_soap_no_auth_required_returns_body(self):
        """A 200 without any challenge is served without auth.

        Documented quirk: the challenge loop tries ALL
        MAX_CHALLENGE_RETRIES attempts even when the server answers 200
        without a WWW-Authenticate header (only exceptions set
        last_exc), then falls into the no-auth path with the LAST
        response — so the scripted 200 must be served for every retry.
        """
        c = _client()
        responses = [_http_response(200, {}, b"<list>3</list>")] * yfps.MAX_CHALLENGE_RETRIES
        sent, ctx = _patch_socket(responses)
        with ctx, patch.object(yfps.time, "sleep", lambda s: None):
            out = c._soap("GetPhonebookList")
        assert "<list>3</list>" in out
        assert len(sent) == yfps.MAX_CHALLENGE_RETRIES  # no extra authed POST

    def test_soap_authenticated_non_200_raises(self):
        c = _client()
        responses = [
            _http_response(401, {"WWW-Authenticate": CHALLENGE}, b""),
            _http_response(403, {}, b"Forbidden"),
        ]
        sent, ctx = _patch_socket(responses)
        with ctx, patch.object(yfps.time, "sleep", lambda s: None):
            with pytest.raises(RuntimeError, match="HTTP 403"):
                c._soap("GetPhonebookList")


class TestGetPhonebookIds:
    def test_parses_id_list(self):
        c = _client()
        soap_body = (
            b'<?xml version="1.0"?>'
            b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            b"<GetPhonebookListResponse><NewPhonebookList>0,1,2</NewPhonebookList>"
            b"</GetPhonebookListResponse></s:Body></s:Envelope>"
        )
        responses = [
            _http_response(401, {"WWW-Authenticate": CHALLENGE}, b""),
            _http_response(200, {}, soap_body),
        ]
        sent, ctx = _patch_socket(responses)
        with ctx, patch.object(yfps.time, "sleep", lambda s: None):
            ids = c.get_phonebook_ids()
        assert ids == [0, 1, 2]
