"""Pytest configuration.

Registers the dash-named main module under a clean import name so that
coverage (--cov=yealink_fritzbox_phonebook_sync) can trace it; the tests
load the file by path via importlib.
"""

import importlib.util
import os
import sys

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
_spec = importlib.util.spec_from_file_location("yealink_fritzbox_phonebook_sync", _MODULE_PATH)
module = importlib.util.module_from_spec(_spec)
sys.modules["yealink_fritzbox_phonebook_sync"] = module
_spec.loader.exec_module(module)
