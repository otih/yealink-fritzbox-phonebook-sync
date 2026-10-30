"""Tests for /all.xml — the combined flat directory.

Many Yealink desk phones (single remote-phonebook slot, e.g. parts of
the T series) want ONE flat directory instead of the menu drill-in.
/all.xml merges every served phonebook into a single
YealinkIPPhoneDirectory, honoring the dedup setting and always sorting.
"""

import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)

PB_A = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<phonebooks><phonebook owner="0" name="Privat">'
    b"<contact><person><realName>Zorro</realName></person>"
    b'<telephony><number type="mobile">+49 170 1</number></telephony></contact>'
    b"<contact><person><realName>Anna</realName></person>"
    b'<telephony><number type="home">+49 30 2</number></telephony></contact>'
    b"</phonebook></phonebooks>"
)
PB_B = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<phonebooks><phonebook owner="1" name="Work">'
    b"<contact><person><realName>Berta</realName></person>"
    b'<telephony><number type="work">+49 89 3</number></telephony></contact>'
    # Same name as in PB_A — cross-phonebook dedup is out of scope by
    # design (dedup is scoped to ONE phonebook), both must appear.
    b"<contact><person><realName>Anna</realName></person>"
    b'<telephony><number type="work">+49 89 4</number></telephony></contact>'
    b"</phonebook></phonebooks>"
)


def _set_state(contacts):
    with yfps.state.lock:
        yfps.state.contacts = dict(contacts)


class TestBuildAllXml:
    def test_merges_all_phonebooks_into_one_directory(self):
        _set_state({1: "A-xml", 2: "B-xml"})
        # Feed the REAL converted XML through the merger
        _, xml_a, _, _ = yfps.convert_single_phonebook(PB_A)
        _, xml_b, _, _ = yfps.convert_single_phonebook(PB_B)
        _set_state({1: xml_a, 2: xml_b})
        out = yfps.build_all_xml()
        assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert out.count("<DirectoryEntry>") == 4  # Zorro, Anna, Berta, Anna
        assert "Zorro" in out and "Berta" in out and "Anna" in out

    def test_sorted_across_phonebooks(self):
        _, xml_a, _, _ = yfps.convert_single_phonebook(PB_A)
        _, xml_b, _, _ = yfps.convert_single_phonebook(PB_B)
        _set_state({1: xml_a, 2: xml_b})
        out = yfps.build_all_xml()
        pos_anna1 = out.find("Anna")
        pos_berta = out.find("Berta")
        pos_zorro = out.find("Zorro")
        assert 0 < pos_anna1 < pos_berta < pos_zorro

    def test_cross_phonebook_same_name_kept_separate(self):
        # Dedup is scoped per phonebook — the two Annas both stay
        _, xml_a, _, _ = yfps.convert_single_phonebook(PB_A)
        _, xml_b, _, _ = yfps.convert_single_phonebook(PB_B)
        _set_state({1: xml_a, 2: xml_b})
        out = yfps.build_all_xml()
        assert out.count("<Name>Anna</Name>") == 2

    def test_empty_state_yields_empty_directory(self):
        _set_state({})
        out = yfps.build_all_xml()
        assert "<DirectoryEntry>" not in out
        assert "<YealinkIPPhoneDirectory>" in out
