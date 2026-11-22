"""Regression test: client-side connection resets must not spam the log.

When a client (typically a Yealink with a short timeout) drops the
connection while the handler is mid-response (wfile.write), the handler
thread raises BrokenPipeError / ConnectionResetError.
socketserver's default handle_error prints a 40-line separator wall
and a full traceback to stderr for EVERY such event — under a flaky
phone this floods the log and, in json log-format environments, breaks
the format with raw stderr output. The fix overrides handle_error on
the SERVER class: expected client disconnects (BrokenPipe,
ConnectionReset, ConnectionAborted, ssl.SSLEOFError) log one warning
line; everything else keeps the full traceback (we must not swallow
real bugs). This test pins both behaviors on the live server.
"""

import errno
import importlib.util
import io
import logging
import os
import socket
import threading

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


def _make_server_with_serve_raises(exc: Exception):
    """Build a server whose handler raises `exc` mid-response (as a client
    disconnect during wfile.write would). Uses the module's real
    _SERVER_CLASS so the production handle_error override is exercised."""
    handler = yfps.PhonebookHandler

    class ExplodingHandler(handler):
        def do_GET(self) -> None:
            raise exc

    srv = yfps._SERVER_CLASS(("127.0.0.1", 0), ExplodingHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


class TestHandleError:
    def _capture_logger(self) -> "io.StringIO":
        """Capture the module logger output while the test runs."""
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        self._handler = handler
        yfps.logger.addHandler(handler)
        yfps.logger.setLevel(logging.WARNING)
        return buf

    def _release_logger(self) -> None:
        yfps.logger.removeHandler(self._handler)

    def test_broken_pipe_logs_one_line(self):
        buf = self._capture_logger()
        srv = _make_server_with_serve_raises(BrokenPipeError(errno.EPIPE, "Broken pipe"))
        try:
            s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
            s.sendall(b"GET /menu.xml HTTP/1.1\r\nHost: x\r\n\r\n")
            s.recv(4096)  # wait for the server to process (and raise)
            s.close()
            # give the handler thread a moment to finish handle_error
            import time

            time.sleep(0.2)
        finally:
            srv.shutdown()
            self._release_logger()
        log_output = buf.getvalue()
        assert "disconnected mid-response" in log_output, (
            "expected the one-line warning, got: %r" % log_output
        )
        assert log_output.count("\n") == 1, "expected exactly one log line, got: %r" % log_output

    def test_unexpected_error_keeps_traceback(self, capsys):
        # Real bugs must still surface WITH traceback — the override must
        # not swallow them. RuntimeError is not a disconnect error.
        srv = _make_server_with_serve_raises(RuntimeError("boom: a real bug"))
        try:
            s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
            s.sendall(b"GET /menu.xml HTTP/1.1\r\nHost: x\r\n\r\n")
            s.recv(4096)
            s.close()
            import time

            time.sleep(0.2)
        finally:
            srv.shutdown()
        err = capsys.readouterr().err
        assert "Traceback" in err, (
            "unexpected errors must keep their full traceback — got: %r" % err
        )
        assert "boom: a real bug" in err
