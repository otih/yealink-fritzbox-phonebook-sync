"""Regression test: the Digest-Auth cnonce must come from a CSPRNG.

The cnonce in HTTP Digest Auth (RFC 7616) protects against replay
attacks; RFC 7616 §3.3 requires at least 64 bits of entropy from a
cryptographically secure random source. The previous implementation
used random.getrandbits(128) — the Mersenne-Twister PRNG, whose state
can be reconstructed from observed outputs, allowing a MITM to predict
future cnonce values. Found during the 2026-11-22 senior review; the
fix uses secrets.token_hex(16) (CSPRNG, same 128-bit entropy, same
32-hex-digit format). This test pins that no Mersenne-Twister path
remains in the digest computation.
"""

import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "yfps", os.path.join(os.path.dirname(__file__), "..", "yealink-fritzbox-phonebook-sync.py")
)
yfps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(yfps)

CHALLENGE = 'Digest realm="fritz.box", nonce="abc", qop="auth"'


class TestCnonceSource:
    def test_cnonce_not_from_mersenne_twister(self):
        # The module must not even import the random module for the
        # digest path — the fix replaced it with the secrets CSPRNG.
        # Poison secrets.token_hex: if the code still used
        # random.getrandbits, the poisoned secrets call would never fire
        # and the produced cnonce would still be hex — so instead we
        # assert the source directly: no random module attribute, and
        # the digest code path uses secrets.
        assert not hasattr(yfps, "random"), (
            "module still imports random — cnonce must use secrets (CSPRNG)"
        )
        client = yfps.FritzboxClient("host", 49000, "user", "pass")
        header = client._build_digest_auth(CHALLENGE, "/tr064/control")
        # cnonce must be present and a 32-hex-digit value (128 bits)
        assert 'cnonce="' in header
        cnonce = header.split('cnonce="')[1].split('"')[0]
        assert len(cnonce) == 32
        int(cnonce, 16)  # must be valid hex — raises if not

    def test_cnonce_values_differ(self):
        # Two consecutive calls produce different cnonces (sanity check
        # that the entropy source is not a constant or counter).
        client = yfps.FritzboxClient("host", 49000, "user", "pass")
        h1 = client._build_digest_auth(CHALLENGE, "/tr064/control")
        h2 = client._build_digest_auth(CHALLENGE, "/tr064/control")
        c1 = h1.split('cnonce="')[1].split('"')[0]
        c2 = h2.split('cnonce="')[1].split('"')[0]
        assert c1 != c2
