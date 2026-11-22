"""Regression test: the external-URL log line must never leak the password.

_external_urls logs the external URL (with embedded credentials) at INFO
level. The password must be masked in that log line — logging the plain
credential would leak it to every reader of the container log (Docker
JSON-file driver, journald, log collectors), contradicting the threat
model's "Credentials never logged" promise. Found during the 2026-11-22
code review; this test pins the fix.
"""

import argparse
import importlib.util
import io
import logging
import os

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)

PASSWORD = "GEHEIM123"


def _capture_external_url_log(server_url: str) -> str:
    """Run _external_urls with auth enabled, return the captured log output."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("fritz-pb-sync")
    logger.setLevel(logging.INFO)
    old_handlers = logger.handlers[:]
    logger.handlers = [handler]
    try:
        args = argparse.Namespace(
            server_url=server_url,
            listen_port=8080,
            auth_user="phone",
            auth_password=PASSWORD,
            dedup_contacts=False,
        )
        _, _external_url = yfps._external_urls(args)
    finally:
        logger.handlers = old_handlers
    return stream.getvalue()


class TestExternalUrlLogMasking:
    def test_password_not_in_log(self):
        log_output = _capture_external_url_log("http://192.168.1.5:8080")
        assert PASSWORD not in log_output, "Password leaked to the log output: %r" % log_output
        # The masked form must be present so operators still see the URL shape
        assert "phone:***@" in log_output

    def test_password_not_in_log_scheme_less_url(self):
        # server_url without :// exercises the partition-less branch
        log_output = _capture_external_url_log("192.168.1.5:8080")
        assert PASSWORD not in log_output, (
            "Password leaked to the log output (scheme-less branch): %r" % log_output
        )
