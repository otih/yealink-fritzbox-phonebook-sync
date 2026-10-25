"""Tests for phone-number normalization."""

import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


class TestNormalizeNumber:
    def test_strips_spaces(self):
        assert yfps._normalize_number("+49 170 123456") == "+49170123456"

    def test_strips_dashes(self):
        assert yfps._normalize_number("+49-170-123456") == "+49170123456"

    def test_strips_slashes_and_parentheses(self):
        assert yfps._normalize_number("+49 (0) 170/123456") == "+49170123456"

    def test_leaves_leading_plus(self):
        assert yfps._normalize_number("+49170123456") == "+49170123456"

    def test_plain_number_unchanged(self):
        assert yfps._normalize_number("07134123456") == "07134123456"

    def test_empty_stays_empty(self):
        assert yfps._normalize_number("") == ""

    def test_sip_uri_untouched(self):
        # Yealink dialable SIP addresses must survive normalization
        assert yfps._normalize_number("500@hd-telefonie.avm.de") == "500@hd-telefonie.avm.de"
