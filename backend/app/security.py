"""Credentials for the parent console, enrolled agents and child dashboards."""

import base64
import hashlib
import hmac
import os
import secrets
import time

from starlette.requests import HTTPConnection

from . import database, models


PARENT_COOKIE = "mmt_parent"
CHILD_COOKIE = "mmt_child"


def _sign(secret, purpose):
    return hmac.new(secret.encode(), purpose.encode(), "sha256").hexdigest()


def hash_pin(pin):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return f"{salt}:{digest.hex()}"


def is_pin_hash(stored):
    salt, _, digest = (stored or "").partition(":")
    if len(salt) != 32 or len(digest) != 128:
        return False
    try:
        bytes.fromhex(salt)
        bytes.fromhex(digest)
    except ValueError:
        return False
    return True


def verify_pin(pin, stored):
    if not is_pin_hash(stored):
        return False
    salt, expected = stored.split(":", 1)
    digest = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return secrets.compare_digest(digest.hex(), expected)


def _session_token(secret, purpose):
    expires = str(int(time.time()) + 8 * 3600)
    return f"{expires}.{_sign(secret, purpose + expires)}"


def _valid_session(token, secret, purpose):
    expires, _, signature = token.partition(".")
    return (
        expires.isascii() and expires.isdecimal() and len(expires) <= 12
        and int(expires) > time.time()
        and secrets.compare_digest(signature.encode(), _sign(secret, purpose + expires).encode())
    )


def parent_session(connection: HTTPConnection):
    password = os.getenv("MMT_PARENT_PASSWORD", "")
    if not password:
        return None
    session = connection.cookies.get(PARENT_COOKIE, "")
    if _valid_session(session, password, "mmt-parent-session"):
        return session
    scheme, _, credential = connection.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "basic":
        try:
            supplied = base64.b64decode(credential, validate=True)
        except ValueError:
            return None
        if secrets.compare_digest(supplied, f"parent:{password}".encode()):
            return _session_token(password, "mmt-parent-session")
    return None


def same_origin(connection: HTTPConnection):
    origin = connection.headers.get("origin")
    scheme = {"ws": "http", "wss": "https"}.get(connection.url.scheme, connection.url.scheme)
    return not origin or origin == f"{scheme}://{connection.url.netloc}"


def dashboard_key(device_token):
    return _sign(device_token, "mmt-dashboard-enrollment")


def dashboard_session(device):
    return f"{device.id}.{_session_token(device.pairing_token, 'mmt-child-session')}"


def resolve_device(connection: HTTPConnection, *, enrollment=False, agent_only=False, child_only=False):
    scheme, _, bearer = connection.headers.get("authorization", "").partition(" ")
    child_id, _, _ = connection.cookies.get(CHILD_COOKIE, "").partition(".")
    device_id, _, key = bearer.partition(".") if scheme.lower() == "bearer" else ("", "", "")
    if not device_id and not enrollment and not agent_only:
        device_id = child_id
    if not device_id:
        return None
    with database.SessionLocal() as db:
        device = db.get(models.Device, device_id)
        if not device or not device.is_paired or not device.pairing_token or not device.child_profile_id:
            return None
        if enrollment:
            valid = secrets.compare_digest(key.encode(), dashboard_key(device.pairing_token).encode())
        elif key and not child_only:
            valid = secrets.compare_digest(key.encode(), device.pairing_token.encode())
        else:
            session = connection.cookies.get(CHILD_COOKIE, "").partition(".")[2]
            valid = device_id == child_id and _valid_session(session, device.pairing_token, "mmt-child-session")
        return device if valid else None
