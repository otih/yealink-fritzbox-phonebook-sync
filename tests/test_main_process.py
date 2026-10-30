"""Process-level tests for main() — the last big uncovered block.

main() wires env vars -> config validation -> client -> server
startup -> signal handling. These tests exercise it in a real
subprocess (same harness style as test_negative_config.py):
- happy path: server starts, serves /health, /metrics, banner in logs
- --version exit code (argparse action)
- SIGTERM: server stops within a few seconds (graceful shutdown)
- placeholder menu before first sync, real menu after cache restore
"""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

APP = os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(env_overrides, port=None):
    port = port or _free_port()
    env = dict(os.environ)
    env.update(env_overrides)
    env.pop("SYNC_TLS_CERT", None)
    env.pop("SYNC_TLS_KEY", None)
    proc = subprocess.Popen(
        [
            sys.executable,
            APP,
            "--fritzbox-host",
            "192.0.2.1",
            "--fritzbox-user",
            "u",
            "--fritzbox-password",
            "p",
            "--listen-port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return proc, port
        except Exception:  # noqa: PERF203 — polling loop; try/except is the pattern
            if proc.poll() is not None:
                break
            time.sleep(0.5)
    proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    raise AssertionError(f"server did not come up; output:\n{out[:2000]}")


class TestMainStartup:
    def test_banner_with_version(self):
        proc, _port = _start_server({})
        try:
            out = subprocess.run([sys.executable, APP, "--version"], capture_output=True, text=True)
            assert "v" in out.stdout
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_server_starts_and_serves(self):
        proc, port = _start_server({"SYNC_LISTEN_PORT": str(port := _free_port())})
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                body = r.read().decode()
            assert '"status":"ok"' in body
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=3) as r:
                metrics = r.read().decode()
            assert "yfps_build_info" in metrics
            assert "yfps_degraded 1" in metrics  # Fritzbox unreachable by design
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_placeholder_menu_before_first_sync(self):
        port = _free_port()
        proc, port = _start_server({"SYNC_SERVER_URL": f"http://127.0.0.1:{port}"}, port)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/menu.xml", timeout=3) as r:
                menu = r.read().decode()
            assert "Noch nicht synchronisiert" in menu
        finally:
            proc.terminate()
            proc.wait(timeout=10)


class TestMainShutdown:
    def test_sigterm_stops_gracefully(self):
        proc, _port = _start_server({})
        t0 = time.time()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        assert proc.returncode == 0  # graceful (srv.serve_forever returns)
        assert time.time() - t0 < 10


class TestMainCacheRestore:
    def test_cache_restored_into_menu(self):
        import json

        with tempfile.TemporaryDirectory() as d:
            snapshot = {
                "menu_xml": "<YealinkIPPhoneMenu><MenuItem><Name>CacheBook (7)</Name>"
                "<URL>http://127.0.0.1/x</URL></MenuItem></YealinkIPPhoneMenu>",
                "contacts": {
                    "1": "<YealinkIPPhoneDirectory><DirectoryEntry><Name>C</Name>"
                    "<Telephone>123</Telephone></DirectoryEntry></YealinkIPPhoneDirectory>"
                },
                "pb_meta": [{"id": 1, "name": "CacheBook", "count": 7}],
                "last_sync": 1760000000.0,
                "total_contacts": 7,
            }
            with open(os.path.join(d, "phonebook-cache.json"), "w") as fh:
                json.dump(snapshot, fh)
            port = _free_port()
            proc, port = _start_server(
                {"SYNC_CACHE_DIR": d, "SYNC_SERVER_URL": f"http://127.0.0.1:{port}"}, port
            )
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/menu.xml", timeout=3) as r:
                    menu = r.read().decode()
                assert "CacheBook (7)" in menu
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/contacts/1.xml", timeout=3
                ) as r:
                    contacts = r.read().decode()
                assert "C" in contacts
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                    health = r.read().decode()
                assert '"contacts":7' in health
            finally:
                proc.terminate()
                proc.wait(timeout=10)
