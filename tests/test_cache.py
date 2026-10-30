"""Tests for the optional on-disk phonebook cache (SYNC_CACHE_DIR).

The cache bridges container restarts while the Fritzbox is unreachable:
after a restart the server serves the last persisted snapshot instead of
the placeholder menu. Pure filesystem round-trips, no Fritzbox needed.
"""

import importlib.util
import json
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


@pytest.fixture()
def cache_dir(tmp_path):
    return str(tmp_path / "cache")


@pytest.fixture()
def populated_state():
    """Fill the module-global state with a deterministic snapshot."""
    with yfps.state.lock:
        yfps.state.menu_xml = "<YealinkIPPhoneMenu><!--cached--></YealinkIPPhoneMenu>"
        yfps.state.contacts = {1: "<YealinkIPPhoneDirectory/>", 2: "<YealinkIPPhoneDirectory/>"}
        yfps.state.pb_meta = [
            {"id": 1, "name": "Work", "count": 10},
            {"id": 2, "name": "Privat", "count": 5},
        ]
        yfps.state.last_sync = 1700000000.5
        yfps.state.total_contacts = 15
        yfps.state.structured_books = {
            1: [("Alice", [("111", "Mobil")])],
            2: [("Bob", [("222", "")])],
        }


class TestSaveCache:
    def test_save_writes_json_snapshot(self, cache_dir, populated_state):
        yfps._save_cache(cache_dir)
        path = yfps._cache_path(cache_dir)
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        # v2: structure, no rendered XML in the file
        assert data["version"] == 2
        assert data["books"]["1"] == [["Alice", [["111", "Mobil"]]]]
        assert data["pb_meta"][0]["name"] == "Work"
        assert data["last_sync"] == 1700000000.5
        assert data["total_contacts"] == 15

    def test_save_creates_missing_directory(self, cache_dir, populated_state):
        assert not os.path.exists(cache_dir)
        yfps._save_cache(cache_dir)
        assert os.path.exists(yfps._cache_path(cache_dir))

    def test_snapshot_file_is_private(self, cache_dir, populated_state):
        # The snapshot contains contact data — it must not be world-readable.
        yfps._save_cache(cache_dir)
        mode = os.stat(yfps._cache_path(cache_dir)).st_mode & 0o777
        assert mode == 0o600


class TestLoadCache:
    def test_load_restores_state(self, cache_dir, populated_state):
        yfps._save_cache(cache_dir)
        # Wipe state as a restart would
        with yfps.state.lock:
            yfps.state.menu_xml = ""
            yfps.state.contacts = {}
            yfps.state.pb_meta = []
            yfps.state.last_sync = 0
            yfps.state.total_contacts = 0
        assert yfps._load_cache(cache_dir) is True
        with yfps.state.lock:
            # v2 restore re-renders from structure with the current URL
            assert "Work" in yfps.state.menu_xml
            assert "<DirectoryEntry>" in yfps.state.contacts[2]
            assert yfps.state.structured_books[1][0][0] == "Alice"
            assert yfps.state.pb_meta[1] == {"id": 2, "name": "Privat", "count": 5}
            assert yfps.state.last_sync == 1700000000.5
            assert yfps.state.total_contacts == 15

    def test_load_missing_file_returns_false(self, cache_dir):
        # Reset state: tests share the module-global state
        with yfps.state.lock:
            yfps.state.menu_xml = ""
        assert yfps._load_cache(cache_dir) is False
        with yfps.state.lock:
            assert yfps.state.menu_xml == ""

    def test_load_corrupt_file_returns_false_and_keeps_state(self, cache_dir, populated_state):
        os.makedirs(cache_dir)
        with open(yfps._cache_path(cache_dir), "w") as fh:
            fh.write("{not json!")
        assert yfps._load_cache(cache_dir) is False
        with yfps.state.lock:
            # State untouched: corrupt cache must never break startup
            assert yfps.state.menu_xml == "<YealinkIPPhoneMenu><!--cached--></YealinkIPPhoneMenu>"


class TestCacheDirValidation:
    def test_cache_path_layout(self, cache_dir):
        assert yfps._cache_path(cache_dir) == os.path.join(cache_dir, "phonebook-cache.json")


class TestCacheV2:
    """v0.15.0 structured cache: full JSON, no XML-in-JSON.

    v1 (pre-0.15.0) stored the RENDERED XML strings — escape soup
    (\\n, \\"), unreadable, and a credential bug: the cached menu_xml
    embedded the OLD auth credentials; after a config change plus
    restart-while-unreachable the phone got stale credentials.
    v2 stores phonebooks as STRUCTURE (name + number/label pairs);
    restore re-renders menu.xml and contacts XML from the structure
    with the CURRENT external URL — same renderer the live sync uses.
    """

    @pytest.fixture()
    def structured_state(self):
        """Books as parsed structure, not rendered XML."""
        with yfps.state.lock:
            yfps.state.menu_xml = "should-be-rebuilt"
            yfps.state.contacts = {1: "<YealinkIPPhoneDirectory/><!--rendered-->"}
            yfps.state.pb_meta = [{"id": 1, "name": "Work", "count": 2}]
            yfps.state.last_sync = 1700000000.5
            yfps.state.total_contacts = 2
            yfps.state.structured_books = {
                1: [
                    ("Anna", [("123", "Mobil")]),
                    ("Berta", [("456", "")]),
                ]
            }

    def test_v2_written_as_structure(self, cache_dir, structured_state):
        yfps._save_cache(cache_dir)
        with open(yfps._cache_path(cache_dir)) as fh:
            data = json.load(fh)
        assert data["version"] == 2
        # NO rendered XML anywhere: the books are plain structures
        assert "YealinkIPPhoneDirectory" not in json.dumps(data)
        assert data["books"]["1"][0][0] == "Anna"
        assert data["books"]["1"][0][1] == [["123", "Mobil"]]
        assert data["pb_meta"][0]["name"] == "Work"
        assert data["last_sync"] == 1700000000.5

    def test_v2_restore_rebuilds_xml_with_current_url(self, cache_dir, structured_state):
        yfps._save_cache(cache_dir)
        with yfps.state.lock:
            yfps.state.menu_xml = ""
            yfps.state.contacts = {}
            yfps.state.structured_books = {}
            yfps.state.pb_meta = []
        assert yfps._load_cache(cache_dir) is True
        # contacts XML rebuilt via the SAME renderer as the live sync
        expected_contacts = "\n".join(
            yfps._render_directory_entries([("Anna", [("123", "Mobil")]), ("Berta", [("456", "")])])
        )
        with yfps.state.lock:
            assert yfps.state.contacts[1].strip() == expected_contacts.strip()
            # menu rebuilt with the CURRENT external URL (the credential fix)
            assert yfps.state.menu_xml  # non-empty, rendered
            assert "should-be-rebuilt" not in yfps.state.menu_xml
            assert yfps.state.structured_books[1][0][0] == "Anna"

    def test_v1_cache_still_loads(self, cache_dir):
        """Backward compat: a v1 cache (rendered XML) must still restore."""
        v1 = {
            "menu_xml": "<YealinkIPPhoneMenu><MenuItem><Name>Old (1)</Name>"
            "<URL>http://old-user:old-pass@10.0.0.9:8080/all.xml</URL>"
            "</MenuItem></YealinkIPPhoneMenu>",
            "contacts": {
                "7": "<YealinkIPPhoneDirectory><DirectoryEntry>"
                "<Name>Legacy Contact</Name><Telephone>999</Telephone>"
                "</DirectoryEntry></YealinkIPPhoneDirectory>"
            },
            "pb_meta": [{"id": 7, "name": "Old", "count": 1}],
            "last_sync": 1600000000.0,
            "total_contacts": 1,
        }
        os.makedirs(cache_dir)
        with open(yfps._cache_path(cache_dir), "w") as fh:
            json.dump(v1, fh)
        assert yfps._load_cache(cache_dir) is True
        with yfps.state.lock:
            assert yfps.state.contacts[7] == v1["contacts"]["7"]
            assert yfps.state.pb_meta[0]["name"] == "Old"

    def test_v2_restored_contacts_served_identically(self, cache_dir, structured_state):
        """The re-rendered XML must be byte-identical to the live-sync path."""
        yfps._save_cache(cache_dir)
        with yfps.state.lock:
            yfps.state.contacts = {}
            yfps.state.structured_books = {}
        yfps._load_cache(cache_dir)
        live_rendered = "\n".join(
            yfps._render_directory_entries([("Anna", [("123", "Mobil")]), ("Berta", [("456", "")])])
        )
        with yfps.state.lock:
            assert yfps.state.contacts[1] == live_rendered
