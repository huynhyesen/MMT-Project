"""Shared hostname policy for the server, browser extension and child Agent."""

import json
import os
import time
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


_additional_hosts = frozenset()
_next_domain_check = 0.0


def additional_adult_hosts():
    """Reload the optional local category list without sending browsing history anywhere."""
    global _additional_hosts, _next_domain_check
    now = time.monotonic()
    if now < _next_domain_check:
        return _additional_hosts
    _next_domain_check = now + 60
    path = os.getenv("MMT_ADULT_DOMAINS_FILE")
    if not path:
        return _additional_hosts
    try:
        with open(path, encoding="utf-8") as source:
            content = source.read(1_048_577)
        if len(content) > 1_048_576:
            return _additional_hosts
        entries = [line.partition("#")[0].strip() for line in content.splitlines()]
        hosts = {normalize_host(entry) for entry in entries if entry}
        if "" not in hosts and len(hosts) <= 10_000:
            _additional_hosts = frozenset(hosts)
    except (OSError, ValueError):
        pass
    return _additional_hosts


def is_adult_host(host):
    labels = host.split(".")
    additional = additional_adult_hosts()
    return any(
        (suffix := ".".join(labels[index:])) in ADULT_HOSTS or suffix in additional
        for index in range(len(labels))
    ) or any(
        pattern.match(f"https://{host}/") for pattern in ADULT_FILTERS
    )


DEFAULT_BLOCKED_HOSTS = frozenset({"youtube.com", "facebook.com", "discord.com", "tiktok.com"})
ADULT_BLOCK_DOMAINS = frozenset(host for host in ADULT_HOSTS if "." in host)


def blocked_hosts_for_agent(rules):
    """Apply the device's effective website rules to the Agent's default block list."""
    blocked = set(DEFAULT_BLOCKED_HOSTS)
    for rule in rules:
        if rule["rule_type"] != "WEBSITE":
            continue
        host = normalize_host(rule["target_value"])
        if not host:
            continue
        if rule["action"] == "BLOCK" or is_adult_host(host):
            blocked.add(host)
        elif rule["action"] == "ALLOW":
            blocked.discard(host)
    return blocked | ADULT_BLOCK_DOMAINS
