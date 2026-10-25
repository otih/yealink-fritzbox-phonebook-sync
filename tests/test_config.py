"""Tests for configuration validation and log/URL helpers."""

import importlib.util
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


class TestValidateConfig:
    def test_valid_config_passes(self):
        cfg = {
            "fritzbox_host": "fritz.box",
            "fritzbox_port": 49000,
            "listen_port": 8080,
            "refresh_interval": 3600,
            "server_url": "http://192.168.1.50:8080",
            "phonebook_id": "1",
        }
        # No exception
        yfps._validate_config(cfg)

    def test_port_too_low_rejected(self):
        cfg = {
            "fritzbox_host": "fritz.box",
            "fritzbox_port": 0,
            "listen_port": 8080,
            "refresh_interval": 3600,
            "server_url": "http://192.168.1.50:8080",
            "phonebook_id": "",
        }
        with pytest.raises(ValueError, match="fritzbox_port"):
            yfps._validate_config(cfg)

    def test_port_too_high_rejected(self):
        cfg = {
            "fritzbox_host": "fritz.box",
            "fritzbox_port": 49000,
            "listen_port": 65536,
            "refresh_interval": 3600,
            "server_url": "http://192.168.1.50:8080",
            "phonebook_id": "",
        }
        with pytest.raises(ValueError, match="listen_port"):
            yfps._validate_config(cfg)

    def test_invalid_phonebook_id_rejected(self):
        cfg = {
            "fritzbox_host": "fritz.box",
            "fritzbox_port": 49000,
            "listen_port": 8080,
            "refresh_interval": 3600,
            "server_url": "http://192.168.1.50:8080",
            "phonebook_id": "1,abc",
        }
        with pytest.raises(ValueError, match="phonebook_id"):
            yfps._validate_config(cfg)

    def test_refresh_interval_must_be_positive(self):
        cfg = {
            "fritzbox_host": "fritz.box",
            "fritzbox_port": 49000,
            "listen_port": 8080,
            "refresh_interval": 0,
            "server_url": "http://192.168.1.50:8080",
            "phonebook_id": "",
        }
        with pytest.raises(ValueError, match="refresh_interval"):
            yfps._validate_config(cfg)


class TestLogLevelParsing:
    def test_valid_levels(self):
        assert yfps._parse_log_level("DEBUG") == "DEBUG"
        assert yfps._parse_log_level("info") == "INFO"

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError, match="log level"):
            yfps._parse_log_level("NOISY")

    def test_empty_defaults_to_info(self):
        assert yfps._parse_log_level("") == "INFO"
