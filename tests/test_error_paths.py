import json
import logging

import pytest
import yealink_fritzbox_phonebook_sync as yfps


class TestParseHttpResponseNegative:
    """Error contracts of the raw HTTP response parser."""

    def test_empty_response(self):
        with pytest.raises(RuntimeError, match="Empty response"):
            yfps._parse_http_response(b"")

    def test_no_separator(self):
        with pytest.raises(RuntimeError, match="no header/body separator"):
            yfps._parse_http_response(b"HTTP/1.1 200 OK\r\nX-Whatever: 1")

    def test_malformed_status_line(self):
        with pytest.raises(RuntimeError, match="Malformed status line"):
            yfps._parse_http_response(b"\r\n\r\nbody")

    def test_non_numeric_status(self):
        raw = b"HTTP/1.1 OK-FINE\r\nContent-Length: 0\r\n\r\n"
        with pytest.raises(RuntimeError, match="Non-numeric HTTP status"):
            yfps._parse_http_response(raw)


class TestFetchPhonebookUrlRefusal:
    """The security path: a non-HTTP phonebook URL from the Fritzbox is
    refused — never fetched. (Trusted device, but the check is the
    last line of defense against a compromised box.)"""

    def test_file_scheme_refused(self):
        client = yfps.FritzboxClient("192.0.2.1", 49000, "u", "p")
        # get_phonebook_url hits the network; simulate its return instead
        client.get_phonebook_url = lambda pid: "file:///etc/passwd"  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="Refusing non-HTTP"):
            client.fetch_phonebook(0)

    def test_ftp_scheme_refused(self):
        client = yfps.FritzboxClient("192.0.2.1", 49000, "u", "p")
        client.get_phonebook_url = lambda pid: "ftp://evil.example/x"  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="Refusing non-HTTP"):
            client.fetch_phonebook(0)


class TestCollectAllEntriesSkipsUnparseable:
    """A corrupt cached book must not take /all.xml down."""

    def test_unparseable_book_skipped(self):
        good_book = (
            b"<phonebook><contact><person><realName>A</realName></person>"
            b'<telephony><number type="home">123</number></telephony>'
            b"</contact></phonebook>"
        )
        contacts = {1: "<<<not xml", 2: yfps.convert_single_phonebook(good_book)[1]}
        entries = yfps._collect_all_entries(contacts)
        # only the parseable book contributes entries
        assert len(entries) == 1


class TestJsonLogFormatter:
    def test_format_emits_json(self):
        rec = logging.LogRecord(
            "yfps-test",
            logging.WARNING,
            "/app/x.py",
            1,
            "hello %s",
            ("world",),
            None,
        )
        out = yfps._JsonLogFormatter().format(rec)
        parsed = json.loads(out)
        assert parsed["level"] == "WARNING"
        assert "hello world" in parsed["msg"]
