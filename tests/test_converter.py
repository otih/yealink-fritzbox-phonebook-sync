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


# Deliberately unsorted: document order is Zorro, Ärger, alfred, Bob.
SORT_PHONEBOOK = b"""<?xml version="1.0" encoding="UTF-8"?>
<phonebooks>
<phonebook owner="0" name="Testbook">
<contact>
<person><realName>Zorro Example</realName></person>
<telephony>
<number type="mobile">+49 170 5550001</number>
</telephony>
</contact>
<contact>
<person><realName>\xc3\x84rger Beispiel</realName></person>
<telephony>
<number type="home">+49 171 5550002</number>
</telephony>
</contact>
<contact>
<person><realName>alfred example</realName></person>
<telephony>
<number type="work">+49 172 5550003</number>
</telephony>
</contact>
<contact>
<person><realName>Bob Beispiel</realName></person>
<telephony>
<number type="home">+49 173 5550004</number>
</telephony>
</contact>
</phonebook>
</phonebooks>"""

# Same contact (same name) twice in one phonebook, different numbers —
# must be merged into one DirectoryEntry.
DUPLICATE_CONTACT_PHONEBOOK = b"""<?xml version="1.0" encoding="UTF-8"?>
<phonebooks>
<phonebook owner="0" name="Testbook">
<contact>
<person><realName>Dup Name</realName></person>
<telephony>
<number type="mobile">+49 170 7770001</number>
</telephony>
</contact>
<contact>
<person><realName>Other Name</realName></person>
<telephony>
<number type="home">+49 711 7770009</number>
</telephony>
</contact>
<contact>
<person><realName>Dup Name</realName></person>
<telephony>
<number type="work">+49 89 7770002</number>
</telephony>
</contact>
</phonebook>
</phonebooks>"""

# Same number twice within one contact (differing labels) — must be
# deduplicated to a single <Telephone>.
DUPLICATE_NUMBER_PHONEBOOK = b"""<?xml version="1.0" encoding="UTF-8"?>
<phonebooks>
<phonebook owner="0" name="Testbook">
<contact>
<person><realName>Number Dup</realName></person>
<telephony>
<number type="mobile">+49 170 8880001</number>
<number type="work">+49 170 8880001</number>
</telephony>
</contact>
</phonebook>
</phonebooks>"""

# Empty label on first occurrence, labeled second — the label should win.
LABEL_RESOLVED_ON_DUP = b"""<?xml version="1.0" encoding="UTF-8"?>
<phonebooks>
<phonebook owner="0" name="Testbook">
<contact>
<person><realName>Label Dup</realName></person>
<telephony>
<number>+49 170 9990001</number>
<number type="mobile">+49 170 9990001</number>
</telephony>
</contact>
</phonebook>
</phonebooks>"""

# Same contact in TWO separate <phonebook> elements — dedup is scoped to
# one phonebook, these must NOT be merged.
TWO_PHONEBOOKS_SAME_CONTACT = b"""<?xml version="1.0" encoding="UTF-8"?>
<phonebooks>
<phonebook owner="0" name="First">
<contact>
<person><realName>Cross Name</realName></person>
<telephony>
<number type="mobile">+49 170 6660001</number>
</telephony>
</contact>
</phonebook>
<phonebook owner="1" name="Second">
<contact>
<person><realName>Cross Name</realName></person>
<telephony>
<number type="work">+49 89 6660002</number>
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
# Tests: sorting (alphabetical, case-insensitive, umlaut-aware)
# ---------------------------------------------------------------------------


class TestSortContacts:
    def test_contacts_sorted_alphabetically(self):
        # Document order: Zorro, Ärger, alfred, Bob.
        # Expected (folded keys): alfred < ärger(arger) < bob < zorro.
        _, contacts, count = yfps.convert_single_phonebook(SORT_PHONEBOOK)
        assert count == 4
        pos_ae = contacts.find("rger Beispiel")  # Ärger
        pos_alfred = contacts.find("alfred example")
        pos_bob = contacts.find("Bob Beispiel")
        pos_zorro = contacts.find("Zorro Example")
        assert -1 not in (pos_ae, pos_alfred, pos_bob, pos_zorro)
        assert pos_alfred < pos_ae < pos_bob < pos_zorro

    def test_sort_case_insensitive(self):
        # alfred (lowercase) must not sort behind Zorro
        _, contacts, _ = yfps.convert_single_phonebook(SORT_PHONEBOOK)
        assert contacts.find("alfred example") < contacts.find("Zorro Example")

    def test_sort_umlaut_german_collation(self):
        # Ä sorts as A — before B(ob), not after Z
        _, contacts, _ = yfps.convert_single_phonebook(SORT_PHONEBOOK)
        assert contacts.find("rger Beispiel") < contacts.find("Bob Beispiel")


# ---------------------------------------------------------------------------
# Tests: deduplication (within a single phonebook)
# ---------------------------------------------------------------------------


class TestDedupContacts:
    """Contact dedup is OPT-IN since v0.9.0: enabled via SYNC_DEDUP_CONTACTS /
    --dedup-contacts; default off reproduces the pre-0.8.0 Fritzbox delivery
    order semantics (only sorting remains always-on)."""

    def test_duplicate_contact_merged_when_enabled(self):
        # Same name twice → one DirectoryEntry with both numbers
        _, contacts, count = yfps.convert_single_phonebook(
            DUPLICATE_CONTACT_PHONEBOOK, dedup_contacts=True
        )
        assert count == 2  # Dup Name (merged) + Other Name
        assert contacts.count("Dup Name") == 1
        # merged entry carries both numbers (normalized form)
        assert "+491707770001" in contacts
        assert "+49897770002" in contacts

    def test_duplicate_contact_numbers_combined_when_enabled(self):
        _, contacts, _ = yfps.convert_single_phonebook(
            DUPLICATE_CONTACT_PHONEBOOK, dedup_contacts=True
        )
        dup_block = contacts[contacts.find("Dup Name") : contacts.find("Other Name")]
        assert dup_block.count("<Telephone") == 2

    def test_duplicate_contact_kept_separate_by_default(self):
        # Default OFF: same-name contacts stay separate entries
        _, contacts, count = yfps.convert_single_phonebook(DUPLICATE_CONTACT_PHONEBOOK)
        assert count == 3  # Dup Name, Other Name, Dup Name again
        assert contacts.count("Dup Name") == 2
        assert "+491707770001" in contacts
        assert "+49897770002" in contacts

    def test_duplicate_number_within_contact_kept_by_default(self):
        # Default OFF: the same number twice in ONE contact stays twice —
        # exact pre-0.8.0 behavior
        _, contacts, count = yfps.convert_single_phonebook(DUPLICATE_NUMBER_PHONEBOOK)
        assert count == 1
        assert contacts.count("<Telephone") == 2  # both occurrences kept
        assert contacts.count("+491708880001") == 2

    def test_duplicate_number_within_contact_deduped_when_enabled(self):
        # Same number twice in one contact (different types) → one element
        _, contacts, count = yfps.convert_single_phonebook(
            DUPLICATE_NUMBER_PHONEBOOK, dedup_contacts=True
        )
        assert count == 1
        assert contacts.count("<Telephone") == 1
        assert contacts.count("+491708880001") == 1

    def test_label_resolved_on_duplicate_number_when_enabled(self):
        # First occurrence unlabeled, second labeled 'mobile' → label wins
        _, contacts, _ = yfps.convert_single_phonebook(LABEL_RESOLVED_ON_DUP, dedup_contacts=True)
        assert contacts.count("<Telephone") == 1
        assert '<Telephone label="Mobil">+491709990001</Telephone>' in contacts

    def test_unlabeled_duplicate_numbers_kept_when_disabled(self):
        # Default OFF: no label resolution happens — both raw entries stay
        _, contacts, _ = yfps.convert_single_phonebook(LABEL_RESOLVED_ON_DUP)
        assert contacts.count("<Telephone") == 2
        assert '<Telephone label="Mobil">+491709990001</Telephone>' in contacts

    def test_dedup_scoped_to_single_phonebook_when_enabled(self):
        # Same contact name in TWO <phonebook> elements → NOT merged
        _, contacts, count = yfps.convert_single_phonebook(
            TWO_PHONEBOOKS_SAME_CONTACT, dedup_contacts=True
        )
        assert count == 2
        assert contacts.count("Cross Name") == 2
        assert "+491706660001" in contacts
        assert "+49896660002" in contacts

    def test_sorting_stays_active_when_dedup_disabled(self):
        # Sorting is always on, independent of the dedup setting
        _, contacts, count = yfps.convert_single_phonebook(SORT_PHONEBOOK)
        assert count == 4
        assert contacts.find("alfred example") < contacts.find("Zorro Example")


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
        # 2 phonebooks + the combined "All contacts" entry
        assert menu.count("<MenuItem>") == 3
        assert "All contacts (198)" in menu
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


class TestAllXmlMenuEntry:
    """The menu gains an 'All contacts' entry pointing at /all.xml,
    making the combined directory discoverable on phones that use the
    menu drill-in (AX83H) instead of a direct single-slot URL."""

    def test_menu_contains_all_contacts_entry(self):
        pbs = [{"id": 1, "name": "Work", "count": 193}]
        menu = yfps.build_menu_xml(pbs, "http://192.168.1.50:8080")
        assert "<Name>All contacts (193)</Name>" in menu
        assert "<URL>http://192.168.1.50:8080/all.xml</URL>" in menu

    def test_all_contacts_entry_comes_first(self):
        pbs = [{"id": 1, "name": "Work", "count": 5}]
        menu = yfps.build_menu_xml(pbs, "http://192.168.1.50:8080")
        pos_all = menu.find("All contacts")
        pos_work = menu.find("Work (5)")
        assert 0 < pos_all < pos_work

    def test_all_contacts_absent_when_no_phonebooks(self):
        # Empty state: no served books -> no all-entry either (it would
        # point at an empty directory; the placeholder flow covers this)
        menu = yfps.build_menu_xml([], "http://192.168.1.50:8080")
        assert "All contacts" not in menu
