"""Regression test: handler threads must not hang forever on stalled clients.

A Slowloris-style client opens connections and sends only a fragment of
the request line, then sends nothing more. Without a socket timeout the
handler thread blocks in rfile.readline() for as long as the attacker
holds the connection open — verified during the 2026-11-22 red-team
audit: 30 stalled connections pinned 30 handler threads indefinitely
(they were still alive 12s later; nothing ever frees them while the
socket is open). Each pinned thread holds a file descriptor and stack
memory; an attacker (or a broken client) in the LAN exhausts threads/FDs
over time. The fix sets the `timeout` class attribute on the handler
(BaseHTTPRequestHandler honors it via socket timeouts): readline()
raises TimeoutError, which the server's quiet-disconnect handler logs
as one line, and the thread is released.

This test pins: a stalled connection is dropped by the SERVER within
the timeout; the handler thread does not stay alive; /health keeps
serving during and after the attack.
"""

import importlib.util
import os
import socket
import threading
import time

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)

# Keep the test fast: the timeout under test is this many seconds.
STALL_TIMEOUT_S = 3


def _start_server() -> tuple[object, int]:
    srv = yfps._make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def _get_health(port: int) -> int:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    s.settimeout(5)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    first_line = data.split(b"\r\n")[0]
    return int(first_line.split()[1])


class TestSlowlorisHandlerTimeout:
    def test_stalled_connection_released_within_timeout(self):
        # Run the test against a SHORT timeout: override the production
        # 30s class attribute for the duration of this test (new handler
        # instances pick it up when the connection is accepted).
        production_timeout = yfps.PhonebookHandler.timeout
        yfps.PhonebookHandler.timeout = STALL_TIMEOUT_S
        srv, port = _start_server()
        threads_before = threading.active_count()
        try:
            # Slowloris: open a connection, send ONE byte of the request
            # line, then send nothing more — the handler thread blocks
            # in readline() until the timeout fires.
            stall = socket.create_connection(("127.0.0.1", port), timeout=10)
            stall.sendall(b"G")
            time.sleep(STALL_TIMEOUT_S / 2)

            # The stalled handler thread is currently pinned...
            active_mid = threading.active_count()
            assert active_mid > threads_before, (
                "expected the stalled connection to pin a handler thread"
            )
            # ...but /health still works under attack:
            assert _get_health(port) == 200, "health blocked by stalled connection"

            # Within the timeout the server drops the stalled connection:
            # the socket is closed (recv returns EOF / errors) ...
            stall.settimeout(STALL_TIMEOUT_S + 5)
            try:
                leftover = stall.recv(1)
                assert leftover in (b"",) or leftover is None, (
                    "server sent unexpected data on the stalled connection"
                )
            except (ConnectionResetError, OSError):
                pass  # server closed hard — also fine
            # ... and the handler thread is released:
            deadline = time.time() + 5
            while threading.active_count() > threads_before and time.time() < deadline:
                time.sleep(0.1)
            assert threading.active_count() <= threads_before, (
                "handler thread still alive %ds after the stall timeout expired"
                % (STALL_TIMEOUT_S + 5)
            )

            # And the server still serves afterwards:
            assert _get_health(port) == 200
        finally:
            yfps.PhonebookHandler.timeout = production_timeout
            srv.shutdown()

    def test_handler_has_timeout_configured(self):
        # The fix: the handler class must set the timeout attribute —
        # None (the BaseHTTPRequestHandler default) means readline()
        # blocks forever on a silent client.
        assert yfps.PhonebookHandler.timeout is not None, (
            "PhonebookHandler.timeout is None — Slowloris pins handler "
            "threads forever (red-team audit 2026-11-22)"
        )
        assert 1 <= yfps.PhonebookHandler.timeout <= 120, (
            "timeout should be a sane operational value (got %r)" % yfps.PhonebookHandler.timeout
        )
