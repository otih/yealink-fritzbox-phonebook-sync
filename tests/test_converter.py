"""Unit tests for yealink-fritzbox-phonebook-sync.

Test strategy:
- Pure functions (converter, XML building, escaping) are tested directly.
- Network-dependent code (FritzboxClient SOAP calls, HTTP handler) is tested
  with mocked sockets/urlopen — no real Fritzbox needed.
- TDD: new features get their tests FIRST (red), then the implementation (green).
"""

import importlib.util
import os

# Load the module by file path — the filename contains dashes and cannot
# be imported via a regular import statement.
_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


# ---------------------------------------------------------------------------
# Fixtures: sample Fritzbox XML data
# ---------------------------------------------------------------------------

SAMPLE_PHONEBOOK = b"""<?xml version="1.0" encoding="UTF-8"?>
<phonebooks>
<phonebook owner="0" name="Testbook">
<contact>
<person><realName>Alice Example</realName></person>
<telephony>
<number type="mobile">+49 170 1234567</number>
<number type="home">+49 7134 987654</number>
</telephony>
</contact>
<contact>
<person><realName>Bob Internal</realName></person>
<telephony>
<number type="intern">**9</number>
<number type="work">+49 89 111222</number>
</telephony>
</contact>
<contact>
<person><realName>Carol NoNumber</realName></person>
<telephony/>
</contact>
</phonebook>
</phonebooks>"""

EMPTY_PHONEBOOK = b"""<?xml version="1.0" encoding="UTF-8"?>
<phonebooks>
<phonebook owner="0" name="Empty">
<contact>
<person><realName>Only Internal</realName></person>
<telephony>
<number type="intern">**600</number>
</telephony>
</contact>
</phonebook>
</phonebooks>"""


# ---------------------------------------------------------------------------
# Tests: _strip_ns
# ---------------------------------------------------------------------------


class TestStripNs:
    def test_strips_namespace(self):
        assert yfps._strip_ns("{urn:dslforum}phonebook") == "phonebook"

    def test_no_namespace(self):
        assert yfps._strip_ns("phonebook") == "phonebook"

    def test_empty(self):
        assert yfps._strip_ns("") == ""


# ---------------------------------------------------------------------------
# Tests: _escape_xml
# ---------------------------------------------------------------------------


class TestEscapeXml:
    def test_escapes_all_special_chars(self):
        assert yfps._escape_xml('&<>"') == "&amp;&lt;&gt;&quot;"

    def test_no_special_chars(self):
        assert yfps._escape_xml("hello") == "hello"

    def test_umlauts_pass_through(self):
        assert yfps._escape_xml("Müller") == "Müller"


# ---------------------------------------------------------------------------
# Tests: convert_single_phonebook
# ---------------------------------------------------------------------------


class TestConvertSinglePhonebook:
    def test_returns_name_and_count(self):
        name, contacts, count = yfps.convert_single_phonebook(SAMPLE_PHONEBOOK)
        assert name == "Testbook"
        assert count == 2  # Carol has no numbers, excluded

    def test_creates_directory_entry(self):
        _, contacts, _ = yfps.convert_single_phonebook(SAMPLE_PHONEBOOK)
        assert "<DirectoryEntry>" in contacts
        assert "</YealinkIPPhoneDirectory>" in contacts
        assert contacts.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_multiple_numbers_per_contact(self):
        _, contacts, _ = yfps.convert_single_phonebook(SAMPLE_PHONEBOOK)
        assert contacts.count("<Telephone") == 3  # Alice: 2, Bob: 1

    def test_type_labels_mapped(self):
        _, contacts, _ = yfps.convert_single_phonebook(SAMPLE_PHONEBOOK)
        assert '<Telephone label="Mobil">' in contacts
        assert '<Telephone label="Festnetz">' in contacts
        assert '<Telephone label="Arbeit">' in contacts

    def test_internal_numbers_filtered(self):
        _, contacts, count = yfps.convert_single_phonebook(SAMPLE_PHONEBOOK)
        assert "**" not in contacts
        assert count == 2  # Bob kept (has work number), but **9 is gone

    def test_contact_without_numbers_excluded(self):
        _, contacts, _ = yfps.convert_single_phonebook(SAMPLE_PHONEBOOK)
        assert "Carol" not in contacts

    def test_xml_escaping_in_names(self):
        # Input XML must be well-formed — special chars come pre-escaped
        # (as the Fritzbox delivers them). Verify they stay escaped in output.
        raw = SAMPLE_PHONEBOOK.replace(b"Alice Example", b"Alice &amp; M&#246;ller")
        _, contacts, _ = yfps.convert_single_phonebook(raw)
        assert "Alice &amp; M\u00f6ller" in contacts

    def test_only_internal_numbers_yields_empty(self):
        _, contacts, count = yfps.convert_single_phonebook(EMPTY_PHONEBOOK)
        assert count == 0
        assert "<DirectoryEntry>" not in contacts


# ---------------------------------------------------------------------------
# Tests: build_menu_xml
# ---------------------------------------------------------------------------


class TestBuildMenuXml:
    def test_menu_lists_all_phonebooks(self):
        pbs = [
            {"id": 0, "name": "Telefonbuch", "count": 5},
            {"id": 1, "name": "Work", "count": 193},
        ]
        menu = yfps.build_menu_xml(pbs, "http://192.168.1.50:8080")
        assert menu.count("<MenuItem>") == 2
        assert "Telefonbuch (5)" in menu
        assert "Work (193)" in menu

    def test_urls_point_to_contacts_endpoint(self):
        pbs = [{"id": 7, "name": "X", "count": 1}]
        menu = yfps.build_menu_xml(pbs, "http://192.168.1.50:8080")
        assert "<URL>http://192.168.1.50:8080/contacts/7.xml</URL>" in menu

    def test_trailing_slash_stripped_from_base(self):
        pbs = [{"id": 1, "name": "X", "count": 1}]
        menu = yfps.build_menu_xml(pbs, "http://192.168.1.50:8080/")
        assert "http://192.168.1.50:8080/contacts/1.xml" in menu

    def test_empty_phonebook_list(self):
        menu = yfps.build_menu_xml([], "http://192.168.1.50:8080")
        assert menu.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert "<YealinkIPPhoneMenu>" in menu


# ---------------------------------------------------------------------------
# Tests: _placeholder_menu
# ---------------------------------------------------------------------------


class TestPlaceholderMenu:
    def test_placeholder_mentions_not_synced(self):
        menu = yfps._placeholder_menu("http://192.168.1.50:8080")
        assert "Noch nicht synchronisiert" in menu


# ---------------------------------------------------------------------------
# Tests: TYPE_LABELS mapping
# ---------------------------------------------------------------------------


class TestTypeLabels:
    def test_known_types(self):
        assert yfps.TYPE_LABELS["mobile"] == "Mobil"
        assert yfps.TYPE_LABELS["home"] == "Festnetz"
        assert yfps.TYPE_LABELS["work"] == "Arbeit"
        assert yfps.TYPE_LABELS["fax"] == "Fax"

    def test_unknown_type_returns_no_label(self):
        assert yfps.TYPE_LABELS.get("somethingelse", "") == ""
