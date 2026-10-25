"""Tests for auth rate limiting and IP allowlist."""

import importlib.util
import os
import time

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)


class TestRateLimit:
    def test_allows_first_failures(self):
        rl = yfps._RateLimiter(max_failures=3, window_seconds=60)
        assert rl.is_allowed("1.2.3.4")
        rl.record_failure("1.2.3.4")
        assert rl.is_allowed("1.2.3.4")
        rl.record_failure("1.2.3.4")
        assert rl.is_allowed("1.2.3.4")

    def test_blocks_after_max_failures(self):
        rl = yfps._RateLimiter(max_failures=3, window_seconds=60)
        for _ in range(3):
            rl.record_failure("1.2.3.4")
        assert not rl.is_allowed("1.2.3.4")

    def test_success_resets_counter(self):
        rl = yfps._RateLimiter(max_failures=3, window_seconds=60)
        for _ in range(3):
            rl.record_failure("1.2.3.4")
        assert not rl.is_allowed("1.2.3.4")
        rl.record_success("1.2.3.4")
        assert rl.is_allowed("1.2.3.4")

    def test_independent_per_ip(self):
        rl = yfps._RateLimiter(max_failures=2, window_seconds=60)
        rl.record_failure("1.1.1.1")
        rl.record_failure("1.1.1.1")
        assert not rl.is_allowed("1.1.1.1")
        assert rl.is_allowed("2.2.2.2")

    def test_window_expires(self):
        rl = yfps._RateLimiter(max_failures=1, window_seconds=0.05)
        rl.record_failure("1.2.3.4")
        assert not rl.is_allowed("1.2.3.4")
        time.sleep(0.08)
        assert rl.is_allowed("1.2.3.4")


class TestIpAllowlist:
    def test_empty_allowlist_allows_all(self):
        al = yfps._IpAllowlist("")
        assert al.is_allowed("192.168.1.50")
        assert al.is_allowed("10.0.0.1")

    def test_exact_ip_allowed(self):
        al = yfps._IpAllowlist("192.168.1.50")
        assert al.is_allowed("192.168.1.50")
        assert not al.is_allowed("192.168.1.51")

    def test_multiple_ips(self):
        al = yfps._IpAllowlist("192.168.1.50, 10.0.0.1")
        assert al.is_allowed("192.168.1.50")
        assert al.is_allowed("10.0.0.1")
        assert not al.is_allowed("192.168.1.99")

    def test_cidr_range(self):
        al = yfps._IpAllowlist("192.168.1.0/24")
        assert al.is_allowed("192.168.1.50")
        assert al.is_allowed("192.168.1.255")
        assert not al.is_allowed("192.168.2.1")
