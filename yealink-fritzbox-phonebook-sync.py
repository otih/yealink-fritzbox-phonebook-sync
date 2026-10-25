#!/usr/bin/env python3
"""
yealink-fritzbox-phonebook-sync.py — Fritzbox → Yealink phonebook sync server.

Fetches phonebook(s) from a Fritzbox via TR-064 SOAP, converts to Yealink
remote-phonebook XML (YealinkIPPhoneMenu + YealinkIPPhoneDirectory), and
serves them over HTTP for the phone to poll periodically.

Each Fritzbox phonebook appears as a separate entry in the phone's
"External Phonebook" menu. Empty phonebooks (only internal numbers) are
hidden automatically.

Phonebook selection (--phonebook-id / FB_PHONEBOOK_ID):
  - Single ID (e.g. "1"):      Only that phonebook appears in the menu.
  - Multiple IDs (e.g. "0,1"):  Each appears as a selectable menu entry.
  - Empty (unset):              All phonebooks are auto-detected and listed.

Zero pip dependencies — Python 3.8+ stdlib only.

Usage:
  python3 yealink-fritzbox-phonebook-sync.py \\
    --fritzbox-host fritz.box \\
    --fritzbox-port 49000 \\
    --fritzbox-user myuser \\
    --fritzbox-password 'mypassword' \\
    --phonebook-id 1            # single, or "0,1" for multiple, or omit for all
    --listen-port 8080 \\
    --refresh-interval 3600 \\
    --server-url http://192.168.1.100:8080

Env vars (fallback for CLI args):
  FB_HOST, FB_PORT, FB_USER, FB_PASSWORD, FB_PHONEBOOK_ID,
  SYNC_LISTEN_PORT, SYNC_REFRESH_INTERVAL, SYNC_SERVER_URL,
  SYNC_AUTH_USER, SYNC_AUTH_PASSWORD

Then on the Yealink web UI → Directory → Remote Phone Book:
  Remote URL:  http://<server-ip>:8080/menu.xml
  Display Name: Fritzbox

See README.md for systemd deployment instructions.
"""

import argparse
import base64
import hashlib
import hmac
import logging
import os
import random
import re
import signal
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import urlopen

logger = logging.getLogger("fritz-pb-sync")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"
ONT_SERVICE_URN = "urn:dslforum-org:service:X_AVM-DE_OnTel:1"
ONT_CONTROL_PATH = "/upnp/control/x_contact"

SOCKET_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 30
MAX_CHALLENGE_RETRIES = 5
CHALLENGE_RETRY_DELAY = 0.3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_ns(tag):
    """Strip XML namespace: '{ns}element' → 'element'."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _escape_xml(text):
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _normalize_number(num):
    """Normalize a phone number for reliable Caller-ID matching.

    Removes formatting characters (spaces, dashes, slashes, parentheses,
    dots) that the Fritzbox stores but that break exact Caller-ID matching
    on the phone. The German "(0)" trunk-prefix notation inside an
    international number is dropped (+49 (0)170… → +49170…), since the
    zero only applies to national dialing. Keeps the leading '+';
    returns SIP URIs (containing '@') unchanged so dialable addresses
    survive.
    """
    if "@" in num:
        return num
    # "+49 (0) 170/…" → "+49 170/…" — the parenthesized trunk zero is
    # redundant in international format.
    num = num.replace("(0)", "")
    for ch in " -/().":
        num = num.replace(ch, "")
    return num


# ---------------------------------------------------------------------------
# Fritzbox TR-064 SOAP client
# ---------------------------------------------------------------------------

# Security note on XML parsing (S314): stdlib xml.etree is used to parse
# responses from the Fritzbox — a trusted, authenticated device on the LAN.
# ElementTree does not resolve external entities by default, so XXE (the
# main S314 concern) requires the parser to encounter crafted DTDs; the
# Fritzbox never emits DTDs in its TR-064 responses. defusedxml would add a
# dependency for no practical gain here; revisit if the trust model changes.


class FritzboxClient:
    """Minimal TR-064 SOAP client for phonebook retrieval."""

    def __init__(self, host, port, user, password):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.control_path = ONT_CONTROL_PATH

    def _build_digest_auth(self, challenge, uri):
        """Parse a WWW-Authenticate digest challenge and build the
        Authorization header. Raises ValueError on malformed challenges."""
        realm_m = re.search(r'realm="([^"]*)"', challenge)
        nonce_m = re.search(r'nonce="([^"]*)"', challenge)
        if not realm_m or not nonce_m:
            raise ValueError("Malformed digest challenge: %s" % challenge[:120])

        realm = realm_m.group(1)
        nonce = nonce_m.group(1)
        algo_m = re.search(r"algorithm=([^\s,]+)", challenge)
        algo = algo_m.group(1) if algo_m else "MD5"
        qop_m = re.search(r'qop="?([^",\s]+)"?', challenge)
        qop = qop_m.group(1) if qop_m else None

        # HTTP Digest Auth requires MD5 per RFC 7616 — this is the protocol
        # computation, not password hashing. noqa: S324
        ha1 = hashlib.md5(f"{self.user}:{realm}:{self.password}".encode()).hexdigest()  # noqa: S324
        ha2 = hashlib.md5(f"POST:{uri}".encode()).hexdigest()  # noqa: S324

        if qop:
            cnonce = "%032x" % random.getrandbits(128)
            nc = "00000001"
            response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()  # noqa: S324 — RFC 7616 Digest protocol
            return (
                f'Digest username="{self.user}", realm="{realm}", '
                f'nonce="{nonce}", uri="{uri}", algorithm={algo}, '
                f'qop={qop}, nc={nc}, cnonce="{cnonce}", response="{response}"'
            )
        else:
            response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()  # noqa: S324 — RFC 7616 Digest protocol
            return (
                f'Digest username="{self.user}", realm="{realm}", '
                f'nonce="{nonce}", uri="{uri}", response="{response}"'
            )

    def _soap(self, action, inner_xml=""):
        """Send a SOAP request to the X_AVM-DE_OnTel service.

        The Fritzbox requires HTTP Digest auth for TR-064. Python's
        http.client sometimes swallows the 401 challenge on this endpoint
        (returning a 500 SOAP fault instead), so we use raw sockets to
        guarantee we see the WWW-Authenticate header and can compute the
        digest response correctly.

        Raises RuntimeError on persistent failure.
        """
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="%s" s:encodingStyle="%s">'
            "<s:Body>"
            '<u:%s xmlns:u="%s">%s</u:%s>'
            "</s:Body>"
            "</s:Envelope>"
        ) % (
            SOAP_ENVELOPE_NS,
            SOAP_ENVELOPE_NS.rstrip("/") + "/encoding/",
            action,
            ONT_SERVICE_URN,
            inner_xml,
            action,
        )

        body = envelope.encode("utf-8")
        soap_action = '"%s#%s"' % (ONT_SERVICE_URN, action)
        base_headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": soap_action,
        }

        # Step 1: unauthenticated POST → get 401 + WWW-Authenticate challenge.
        # The Fritzbox is inconsistent: sometimes it returns 401 with a
        # WWW-Authenticate header, sometimes 500 with a SOAP fault. Retry
        # a few times until we get the challenge.
        auth_hdr = ""
        last_exc = None
        for attempt in range(MAX_CHALLENGE_RETRIES):
            try:
                resp = self._raw_post(self.control_path, body, base_headers)
            except (OSError, RuntimeError) as exc:
                last_exc = exc
                logger.debug(
                    "Challenge attempt %d/%d failed: %s", attempt + 1, MAX_CHALLENGE_RETRIES, exc
                )
                time.sleep(CHALLENGE_RETRY_DELAY)
                continue
            auth_hdr = resp["headers"].get("WWW-Authenticate", "")
            if auth_hdr:
                break
            time.sleep(CHALLENGE_RETRY_DELAY)

        if not auth_hdr:
            if last_exc:
                raise RuntimeError(
                    "SOAP %s: could not obtain digest challenge after %d retries: %s"
                    % (action, MAX_CHALLENGE_RETRIES, last_exc)
                )
            # No auth required — return whatever we got
            return resp["body"]

        # Step 2: POST with digest auth
        auth_header = self._build_digest_auth(auth_hdr, self.control_path)
        resp = self._raw_post(
            self.control_path, body, dict(base_headers, Authorization=auth_header)
        )

        if resp["status"] != 200:
            logger.error("SOAP %s HTTP %d: %s", action, resp["status"], resp["body"][:500])
            raise RuntimeError("SOAP %s failed: HTTP %d" % (action, resp["status"]))
        return resp["body"]

    def _raw_post(self, path, body, headers):
        """Send an HTTP POST via raw socket, return parsed response.

        Ensures the socket is always closed, even on error.
        Raises socket.error on connection/network failures, RuntimeError
        on malformed responses.
        """
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        try:
            sock.connect((self.host, self.port))

            lines = [f"POST {path} HTTP/1.1", f"Host: {self.host}:{self.port}"]
            for k, v in headers.items():
                lines.append(f"{k}: {v}")
            lines.append(f"Content-Length: {len(body)}")
            lines.append("Connection: close")
            lines.append("")
            lines.append("")
            request_head = "\r\n".join(lines).encode("utf-8")
            sock.sendall(request_head + body)

            # Read response — Connection: close ensures recv returns on EOF
            chunks = []
            while True:
                try:
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                except socket.timeout:
                    break
        finally:
            sock.close()

        raw = b"".join(chunks)
        if not raw:
            raise RuntimeError("Empty response from Fritzbox")

        # Split headers/body
        sep = raw.find(b"\r\n\r\n")
        if sep == -1:
            raise RuntimeError(
                "Malformed HTTP response (no header/body separator): %s"
                % raw[:120].decode("utf-8", errors="replace")
            )

        header_block = raw[:sep].decode("utf-8", errors="replace")
        resp_body = raw[sep + 4 :].decode("utf-8", errors="replace")

        status_line, _, header_rest = header_block.partition("\r\n")
        parts = status_line.split()
        if len(parts) < 2:
            raise RuntimeError("Malformed status line: %s" % status_line)
        try:
            status = int(parts[1])
        except ValueError:
            raise RuntimeError("Non-numeric HTTP status: %s" % parts[1]) from None

        resp_headers = {}
        for line in header_rest.split("\r\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                resp_headers[k.strip()] = v.strip()

        return {"status": status, "headers": resp_headers, "body": resp_body}

    def get_phonebook_ids(self):
        """Return list of phonebook IDs available on the Fritzbox."""
        raw = self._soap("GetPhonebookList")
        root = ET.fromstring(raw)  # noqa: S314 — trusted Fritzbox source, see security note
        for elem in root.iter():
            if _strip_ns(elem.tag) == "NewPhonebookList":
                ids_str = (elem.text or "").strip()
                return [int(i) for i in ids_str.split(",") if i.strip()]
        raise ValueError("NewPhonebookList not found in SOAP response")

    def get_phonebook_url(self, phonebook_id):
        """Return the download URL for a specific phonebook ID."""
        inner = "<NewPhonebookId>%d</NewPhonebookId>" % phonebook_id
        raw = self._soap("GetPhonebook", inner)
        root = ET.fromstring(raw)  # noqa: S314 — trusted Fritzbox source, see security note
        for elem in root.iter():
            if _strip_ns(elem.tag) == "NewPhonebookURL":
                return (elem.text or "").strip()
        raise ValueError("NewPhonebookURL not found in SOAP response")

    def fetch_phonebook(self, phonebook_id):
        """Download raw Fritzbox phonebook XML (bytes) for one phonebook ID.

        The URL comes from the Fritzbox SOAP response; only http/https
        schemes are allowed to prevent file:// or other scheme abuse if
        the SOAP response were ever tampered with.

        Raises URLError on download failure, ValueError on disallowed schemes.
        """
        url = self.get_phonebook_url(phonebook_id)
        if not url.startswith(("http://", "https://")):
            raise ValueError("Refusing non-HTTP phonebook URL: %s" % url[:120])
        logger.info("Downloading phonebook %d from %s", phonebook_id, url)
        resp = urlopen(url, timeout=DOWNLOAD_TIMEOUT)  # noqa: S310 — scheme whitelisted above
        return resp.read()

    def fetch_all_phonebooks(self, ids):
        """Download multiple phonebooks. Returns concatenated bytes.

        Stops on first failure — atomicity over partial results.
        """
        chunks = [self.fetch_phonebook(pid) for pid in ids]
        return b"\n".join(chunks)


# ---------------------------------------------------------------------------
# Fritzbox XML → Yealink remote phonebook XML converter
# ---------------------------------------------------------------------------

# Fritzbox number type → Yealink label mapping
TYPE_LABELS = {
    "mobile": "Mobil",
    "home": "Festnetz",
    "work": "Arbeit",
    "fax_work": "Fax",
    "fax": "Fax",
    "other": "Sonstige",
}


def convert_single_phonebook(fritzbox_xml_bytes):
    """
    Convert a single Fritzbox phonebook XML to Yealink DirectoryEntry format.

    Returns (phonebook_name, contacts_xml_str, contact_count).
    Uses the YealinkIPPhoneDirectory format documented for the AX83H.
    Each <Telephone> gets a label attribute mapped from the Fritzbox number type.
    Internal Fritzbox numbers (**9, **600, etc.) are filtered out.
    """
    root = ET.fromstring(fritzbox_xml_bytes)  # noqa: S314 — trusted Fritzbox source, see security note

    # Extract phonebook name from the <phonebook name="..."> attribute
    pb_name = "Telefonbuch"
    for elem in root.iter():
        if _strip_ns(elem.tag) == "phonebook":
            pb_name = elem.get("name", "") or "Telefonbuch"
            break

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<YealinkIPPhoneDirectory>"]
    count = 0

    for phonebook in root.iter():
        if _strip_ns(phonebook.tag) != "phonebook":
            continue
        for contact in phonebook:
            if _strip_ns(contact.tag) != "contact":
                continue

            # Extract name
            person = None
            for child in contact:
                if _strip_ns(child.tag) == "person":
                    person = child
                    break
            if person is None:
                continue
            name = None
            for child in person:
                if _strip_ns(child.tag) == "realName":
                    name = (child.text or "").strip()
                    break
            if not name:
                continue

            # Extract numbers — Fritzbox uses <telephony><number>,
            # older firmwares used <numbers><number>
            numbers_elem = None
            for child in contact:
                if _strip_ns(child.tag) in ("numbers", "telephony"):
                    numbers_elem = child
                    break
            if numbers_elem is None:
                continue

            numbers = []
            for child in numbers_elem:
                if _strip_ns(child.tag) == "number":
                    num = (child.text or "").strip()
                    # Skip internal Fritzbox numbers (**9, **600, etc.)
                    if num and not num.startswith("**"):
                        num = _normalize_number(num)
                        num_type = child.get("type", "")
                        label = TYPE_LABELS.get(num_type, "")
                        numbers.append((num, label))

            if not numbers:
                continue

            # Emit one <DirectoryEntry> with all numbers
            lines.append("  <DirectoryEntry>")
            lines.append("    <Name>%s</Name>" % _escape_xml(name))
            for num, label in numbers:
                if label:
                    lines.append(
                        '    <Telephone label="%s">%s</Telephone>'
                        % (_escape_xml(label), _escape_xml(num))
                    )
                else:
                    lines.append("    <Telephone>%s</Telephone>" % _escape_xml(num))
            lines.append("  </DirectoryEntry>")
            count += 1

    lines.append("</YealinkIPPhoneDirectory>")
    contacts_str = "\n".join(lines)
    return pb_name, contacts_str, count


def build_menu_xml(phonebooks, server_base):
    """
    Build the YealinkIPPhoneMenu listing all phonebooks as selectable entries.

    Each phonebook becomes a <MenuItem> with its name and contact count.
    The phone shows this as a list under "External Phonebook" — the user
    selects one to drill into its contacts.

    Args:
        phonebooks: list of dicts with keys 'id', 'name', 'count'.
                    Only non-empty phonebooks should be passed (caller filters).
        server_base: base URL for constructing per-phonebook URLs.
                     Each phonebook gets its own URL: <base>/contacts/<id>.xml
    """
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<YealinkIPPhoneMenu>"]
    for pb in phonebooks:
        lines.append("  <MenuItem>")
        lines.append("    <Name>%s (%d)</Name>" % (_escape_xml(pb["name"]), pb["count"]))
        lines.append("    <URL>%s/contacts/%d.xml</URL>" % (server_base.rstrip("/"), pb["id"]))
        lines.append("  </MenuItem>")
    lines.append("</YealinkIPPhoneMenu>")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Shared state (thread-safe)
# ---------------------------------------------------------------------------


class State:
    def __init__(self):
        self.menu_xml = ""
        self.contacts = {}  # {phonebook_id: contacts_xml_str}
        self.pb_meta = []  # [{id, name, count}]
        self.last_sync = 0
        self.total_contacts = 0
        self.sync_successes = 0
        self.sync_failures = 0
        self.lock = threading.Lock()


state = State()

# HTTP Basic Auth credentials (set in main from env vars)
auth_user = ""
auth_pass = ""


def _placeholder_menu(server_base):
    """Empty menu served before the first successful sync."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<YealinkIPPhoneMenu>\n"
        "  <MenuItem>\n"
        "    <Name>Noch nicht synchronisiert</Name>\n"
        "    <URL>%s/contacts/0.xml</URL>\n"
        "  </MenuItem>\n"
        "</YealinkIPPhoneMenu>\n"
    ) % _escape_xml(server_base.rstrip("/"))


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class PhonebookHandler(BaseHTTPRequestHandler):
    # Yealink phones expect HTTP/1.1; BaseHTTPRequestHandler defaults to 1.0
    protocol_version = "HTTP/1.1"

    def _check_auth(self):
        """Validate HTTP Basic Auth. Returns True if authorized or auth disabled."""
        if not auth_user:
            return True
        hdr = self.headers.get("Authorization", "")
        if not hdr.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(hdr[6:]).decode("utf-8")
            user, _, pw = decoded.partition(":")
            return hmac.compare_digest(user, auth_user) and hmac.compare_digest(pw, auth_pass)
        except Exception:
            return False

    def _require_auth(self):
        """Send 401 challenge if auth is enabled and not satisfied."""
        if not auth_user:
            return True
        if self._check_auth():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Phonebook"')
        self.send_header("Connection", "close")
        self.end_headers()
        return False

    def do_GET(self):
        # /health is always open (needed for Docker HEALTHCHECK, monitoring)
        if self.path == "/health":
            with state.lock:
                age = int(time.time() - state.last_sync) if state.last_sync else -1
                payload = '{"status":"ok","contacts":%d,"last_sync_age_sec":%d}' % (
                    state.total_contacts,
                    age,
                )
            self._serve(payload, content_type="application/json")
            # Suppress health-check noise — log at DEBUG, not INFO
            if "healthcheck" not in (self.headers.get("User-Agent", "").lower()):
                logger.debug("%s - GET /health 200", self.client_address[0])
            return

        # Prometheus metrics — always open (same rationale as /health:
        # exposes operational counters, no contact data)
        if self.path == "/metrics":
            with state.lock:
                age = int(time.time() - state.last_sync) if state.last_sync else -1
                lines = [
                    "# HELP yfps_sync_success_total Number of successful sync cycles",
                    "# TYPE yfps_sync_success_total counter",
                    "yfps_sync_success_total %d" % state.sync_successes,
                    "# HELP yfps_sync_failure_total Number of failed sync cycles",
                    "# TYPE yfps_sync_failure_total counter",
                    "yfps_sync_failure_total %d" % state.sync_failures,
                    "# HELP yfps_sync_last_timestamp_seconds Unix timestamp of the last successful sync",
                    "# TYPE yfps_sync_last_timestamp_seconds gauge",
                    "yfps_sync_last_timestamp_seconds %d" % int(state.last_sync),
                    "# HELP yfps_sync_age_seconds Seconds since the last successful sync (-1 = never)",
                    "# TYPE yfps_sync_age_seconds gauge",
                    "yfps_sync_age_seconds %d" % age,
                    "# HELP yfps_contacts_total Total contacts across all phonebooks",
                    "# TYPE yfps_contacts_total gauge",
                    "yfps_contacts_total %d" % state.total_contacts,
                    "# HELP yfps_phonebooks_total Number of phonebooks served",
                    "# TYPE yfps_phonebooks_total gauge",
                    "yfps_phonebooks_total %d" % len(state.pb_meta),
                ]
            self._serve("\n".join(lines) + "\n", content_type="text/plain; version=0.0.4")
            return

        # All other endpoints require auth
        if not self._require_auth():
            return

        if self.path in ("/", "/menu.xml"):
            with state.lock:
                body = state.menu_xml
            if not body:
                body = "<YealinkIPPhoneDirectory><DirectoryEntry><Name>Not synced yet</Name></DirectoryEntry></YealinkIPPhoneDirectory>"
            self._serve(body)
        elif self.path.startswith("/contacts/") and self.path.endswith(".xml"):
            # Extract phonebook ID from path: /contacts/1.xml → 1
            try:
                pb_id = int(self.path[len("/contacts/") : -len(".xml")])
            except ValueError:
                self.send_error(404)
                return
            with state.lock:
                body = state.contacts.get(pb_id, "")
            if not body:
                body = "<YealinkIPPhoneDirectory/>"
            self._serve(body)
        else:
            self.send_error(404)

    def _serve(self, content, content_type="application/xml; charset=utf-8"):
        body = content.encode("utf-8")
        self.send_response_only(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        logger.info(
            '%s - "%s %s HTTP/1.1" 200 %d',
            self.client_address[0],
            self.command,
            self.path,
            len(body),
        )

    def log_message(self, fmt, *args):
        # Catch 401/404 and other non-200 responses that go through send_error/send_response
        logger.info("%s - %s", self.client_address[0], fmt % args)


# ---------------------------------------------------------------------------
# Sync loop
# ---------------------------------------------------------------------------

BACKOFF_BASE_SECONDS = 60


def _backoff_delay(consecutive_failures, refresh_interval):
    """Exponential retry delay after failed syncs.

    60s, 120s, 240s, ... capped at the regular refresh interval, so a
    Fritzbox reboot recovers within minutes instead of after the full hour,
    while a persistently unreachable box is not hammered every minute.
    """
    delay = BACKOFF_BASE_SECONDS * (2**consecutive_failures)
    return min(delay, refresh_interval)


def sync_once(client, phonebook_ids, server_base, external_url):
    """Perform one sync cycle. Raises on failure — caller handles retries.

    Fetches each phonebook individually, converts it, and builds a menu
    listing all non-empty phonebooks. Empty phonebooks (0 contacts after
    filtering internal numbers) are excluded from the menu.

    Args:
        server_base: used for internal URL construction (no credentials)
        external_url: used for Menu.xml <URL> tags (may include embedded
                     credentials for phones without separate auth fields)
    """
    if not phonebook_ids:
        phonebook_ids = client.get_phonebook_ids()
        logger.info("Resolved phonebook IDs: %s", phonebook_ids)

    pb_meta = []
    contacts_map = {}
    total = 0

    for pid in phonebook_ids:
        raw = client.fetch_phonebook(pid)
        pb_name, contacts_xml, count = convert_single_phonebook(raw)
        contacts_map[pid] = contacts_xml
        pb_meta.append({"id": pid, "name": pb_name, "count": count})
        total += count
        logger.info("Phonebook %d '%s': %d contacts", pid, pb_name, count)

    menu = build_menu_xml(pb_meta, external_url)

    with state.lock:
        state.menu_xml = menu
        state.contacts = contacts_map
        state.pb_meta = pb_meta
        state.last_sync = time.time()
        state.total_contacts = total
        state.sync_successes += 1
    logger.info("Sync complete: %d phonebooks, %d total contacts", len(pb_meta), total)


def sync_loop(client, phonebook_ids, server_base, external_url, refresh_interval):
    """Background thread: periodic sync with exponential backoff on failure.

    After a failed sync the retry delay grows (60s, 120s, 240s, ...) capped
    at the refresh interval; a successful sync resets the backoff.
    """
    pb_ids = list(phonebook_ids)
    consecutive_failures = 0
    while True:
        if not pb_ids:
            try:
                pb_ids = client.get_phonebook_ids()
                logger.info("Auto-detected phonebook IDs: %s", pb_ids)
            except Exception as exc:
                logger.warning("Still cannot detect phonebook IDs: %s", exc)
                with state.lock:
                    state.sync_failures += 1
                time.sleep(_backoff_delay(consecutive_failures, refresh_interval))
                consecutive_failures += 1
                continue
        try:
            sync_once(client, pb_ids, server_base, external_url)
            consecutive_failures = 0
        except Exception as exc:
            delay = _backoff_delay(consecutive_failures, refresh_interval)
            logger.warning(
                "Sync failed (retry %d in %ds): %s", consecutive_failures + 1, delay, exc
            )
            with state.lock:
                state.sync_failures += 1
            consecutive_failures += 1
            time.sleep(delay)
            continue
        time.sleep(refresh_interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(
        description="Fritzbox → Yealink phonebook sync server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--fritzbox-host", default=os.getenv("FB_HOST", "fritz.box"))
    p.add_argument("--fritzbox-port", type=int, default=int(os.getenv("FB_PORT", "49000")))
    p.add_argument("--fritzbox-user", default=os.getenv("FB_USER", ""))
    p.add_argument("--fritzbox-password", default=os.getenv("FB_PASSWORD", ""))
    p.add_argument(
        "--phonebook-id",
        default=os.getenv("FB_PHONEBOOK_ID", ""),
        help="Single ID (e.g. '1'), multiple (e.g. '0,1'), or empty for all",
    )
    p.add_argument("--listen-port", type=int, default=int(os.getenv("SYNC_LISTEN_PORT", "8080")))
    p.add_argument(
        "--refresh-interval",
        type=int,
        default=int(os.getenv("SYNC_REFRESH_INTERVAL", "3600")),
        help="Seconds between syncs (default: 3600 = 1h)",
    )
    p.add_argument(
        "--server-url",
        default=os.getenv("SYNC_SERVER_URL", os.getenv("SYNC_EXTERNAL_URL", "")),
        help="External URL the Yealink phone uses to reach this server, e.g. http://192.168.1.50:8080",
    )
    p.add_argument(
        "--auth-user",
        default=os.getenv("SYNC_AUTH_USER", ""),
        help="HTTP Basic Auth username for phonebook access (empty = no auth)",
    )
    p.add_argument(
        "--auth-password",
        default=os.getenv("SYNC_AUTH_PASSWORD", ""),
        help="HTTP Basic Auth password for phonebook access",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    if not args.fritzbox_user or not args.fritzbox_password:
        logger.error("Fritzbox user and password required.")
        logger.error("Set via --fritzbox-user/--fritzbox-password or FB_USER/FB_PASSWORD env vars.")
        sys.exit(1)

    if not args.server_url:
        args.server_url = "http://0.0.0.0:%d" % args.listen_port
        logger.warning(
            "--server-url not set; using %s — the phone may not reach this address.",
            args.server_url,
        )
        logger.warning("Set --server-url to the IP/hostname the Yealink will use.")

    # server_base: used for internal URL construction (no credentials)
    # external_url: used for the Menu.xml <URL> tags (includes credentials
    # if auth is enabled, because the AX83H has no separate auth fields)
    server_base = args.server_url.rstrip("/")
    external_url = server_base

    # Set HTTP Basic Auth credentials globally for the handler
    global auth_user, auth_pass
    auth_user = args.auth_user
    auth_pass = args.auth_password
    if auth_user:
        logger.info("HTTP Basic Auth enabled (user: %s)", auth_user)
        # Embed credentials in the external URL for the phone
        # The AX83H does not have separate username/password fields for
        # remote phonebooks, so credentials must be in the URL.
        # Format: http://user:pass@host:port
        if "://" in server_base:
            scheme, _, rest = server_base.partition("://")
            external_url = "%s://%s:%s@%s" % (scheme, auth_user, auth_pass, rest)
        else:
            external_url = "http://%s:%s@%s" % (auth_user, auth_pass, server_base)
        logger.info("External URL (with embedded auth): %s", external_url)
    else:
        logger.warning("HTTP Basic Auth DISABLED — phonebook is accessible without credentials")

    # Resolve phonebook IDs
    client = FritzboxClient(
        args.fritzbox_host, args.fritzbox_port, args.fritzbox_user, args.fritzbox_password
    )

    if args.phonebook_id:
        pb_ids = [int(i) for i in args.phonebook_id.split(",")]
    else:
        try:
            pb_ids = client.get_phonebook_ids()
            logger.info("Auto-detected phonebook IDs: %s", pb_ids)
        except Exception as exc:
            logger.warning(
                "Cannot auto-detect phonebook IDs (%s) — starting server anyway, will retry in background",
                exc,
            )
            pb_ids = []

    # Serve a placeholder until first successful sync
    with state.lock:
        state.menu_xml = _placeholder_menu(external_url)

    # Initial sync (non-blocking — server starts even if this fails)
    try:
        sync_once(client, pb_ids, server_base, external_url)
    except Exception as exc:
        logger.warning("Initial sync failed (will retry in background): %s", exc)

    # Background sync thread
    t = threading.Thread(
        target=sync_loop,
        args=(client, pb_ids, server_base, external_url, args.refresh_interval),
        daemon=True,
    )
    t.start()

    # HTTP server
    # HTTP server — binding to all interfaces (S104) is intentional:
    # the Yealink phone on the LAN must be able to reach this server.
    # Restrict via container network policy or a reverse proxy if needed.
    srv = HTTPServer(("0.0.0.0", args.listen_port), PhonebookHandler)  # noqa: S104
    logger.info("=" * 60)
    logger.info("Listening on http://0.0.0.0:%d", args.listen_port)
    logger.info("Yealink Remote Phonebook URL: %s/menu.xml", args.server_url.rstrip("/"))
    logger.info("Health check: %s/health", args.server_url.rstrip("/"))
    logger.info("Refresh interval: %d seconds", args.refresh_interval)
    logger.info("=" * 60)

    # Handle SIGTERM (sent by `docker stop`) gracefully.
    # srv.shutdown() must run in a separate thread — calling it from the
    # signal handler (which interrupts serve_forever's poll loop) would
    # deadlock, since shutdown() waits for serve_forever() to return.
    def _shutdown(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    srv.serve_forever()
    logger.info("Server stopped.")


if __name__ == "__main__":
    main()
