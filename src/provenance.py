"""Provenance certificate — a verifiable "Verified Human" credential.

The credential is earned, not guessed:
  1. The creator requests a one-time random challenge phrase.
  2. They TYPE it live (the behavioral signal must read typed_live, not pasted),
     proving a human is actively present.
  3. On success the server issues an HMAC-SHA256 certificate binding
     content_id + creator_id + issued_at. It is tamper-evident: change any field
     and the signature no longer verifies.

Honest scope: this proves "a human completed a live typing attestation for this
content", not absolute authorship. It is a capture-time provenance step — far
stronger than post-hoc statistical detection, but not a DRM guarantee.

The signing secret comes from PROVENANCE_SECRET (set it in production). A default
is used for local dev so the demo runs out of the box.
"""
import hashlib
import hmac
import json
import os
import secrets

_SECRET = os.environ.get("PROVENANCE_SECRET", "dev-only-change-me").encode()

# short, easy-to-type challenge words (typing them live is the human proof)
_WORDS = [
    "amber", "river", "candle", "orbit", "meadow", "copper", "lantern", "pebble",
    "willow", "harbor", "cipher", "violet", "quartz", "thistle", "ember", "marble",
]


def new_challenge_phrase(n=4):
    """Return a random space-joined phrase the creator must type live."""
    return " ".join(secrets.choice(_WORDS) for _ in range(n))


def _payload(content_id, creator_id, issued_at, method):
    # canonical, sorted JSON so the signature is deterministic
    return json.dumps(
        {"content_id": content_id, "creator_id": creator_id,
         "issued_at": issued_at, "method": method},
        sort_keys=True, separators=(",", ":"),
    )


def sign(content_id, creator_id, issued_at, method="typed_challenge"):
    """Return (signature_hex, cert_id) for a certificate payload."""
    msg = _payload(content_id, creator_id, issued_at, method).encode()
    sig = hmac.new(_SECRET, msg, hashlib.sha256).hexdigest()
    return sig, sig[:16]  # cert_id = first 16 hex chars


def verify(content_id, creator_id, issued_at, signature, method="typed_challenge"):
    """Constant-time check that a stored certificate is authentic + untampered."""
    expected, _ = sign(content_id, creator_id, issued_at, method)
    return hmac.compare_digest(expected, signature)


def normalize(s):
    """Loose match for the typed challenge (case/space-insensitive)."""
    return " ".join((s or "").lower().split())
