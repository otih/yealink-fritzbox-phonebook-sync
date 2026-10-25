"""TDD: retry backoff schedule. RED first — _backoff_delay does not exist yet."""

import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


def test_backoff_grows_exponentially():
    # consecutive failures: 0 -> 60s, 1 -> 120s, 2 -> 240s ...
    assert yfps._backoff_delay(0, 3600) == 60
    assert yfps._backoff_delay(1, 3600) == 120
    assert yfps._backoff_delay(2, 3600) == 240


def test_backoff_caps_at_refresh_interval():
    assert yfps._backoff_delay(10, 3600) == 3600
    assert yfps._backoff_delay(100, 3600) == 3600


def test_backoff_first_attempt_smaller_than_interval():
    assert yfps._backoff_delay(0, 3600) < 3600
