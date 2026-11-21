"""Shared hostname policy for the server, browser extension and child Agent."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


RULES = json.loads(
    (Path(__file__).resolve().parents[1] / "browser-extension" / "adult-rules.json").read_text()
)
ADULT_HOSTS = frozenset(
    host for rule in RULES for host in rule["condition"].get("requestDomains", [])
)
ADULT_FILTERS = tuple(
    re.compile(rule["condition"]["regexFilter"], re.ASCII | re.IGNORECASE)
    for rule in RULES if "regexFilter" in rule["condition"]
)
HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)


def normalize_host(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    try:
        parsed = urlsplit(value if "://" in value else "//" + value)
        if parsed.scheme not in {"", "http", "https"} or parsed.username is not None:
            return ""
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return ""
    if len(host) > 253 or "." not in host or not all(HOST_LABEL.fullmatch(part) for part in host.split(".")):
        return ""
    return host.removeprefix("www.") if host.count(".") > 1 else host


def is_adult_host(host):
    labels = host.split(".")
    return any(".".join(labels[index:]) in ADULT_HOSTS for index in range(len(labels))) or any(
        pattern.match(f"https://{host}/") for pattern in ADULT_FILTERS
    )
