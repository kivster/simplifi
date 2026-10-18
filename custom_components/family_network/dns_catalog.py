"""Versioned, independently curated DNS samples; observations, never blocklists."""

from copy import deepcopy
from typing import Any

from .models import FamilyError

# Small service-homepage samples. Resolving these names does not visit their sites,
# test every service hostname, or establish a whole-category/device verdict.
CATEGORIES: dict[str, dict[str, Any]] = {
    "video": {
        "name": "Video",
        "dpi": 4,
        "icon": "mdi:play-circle-outline",
        "domains": ["youtube.com", "netflix.com", "vimeo.com"],
        "filters": ["STREAMING_MEDIA"],
    },
    "social": {
        "name": "Social",
        "dpi": 24,
        "icon": "mdi:account-group-outline",
        "domains": ["facebook.com", "instagram.com", "tiktok.com"],
        "filters": ["SOCIAL_NETWORKS"],
    },
    "gaming": {
        "name": "Gaming",
        "dpi": 8,
        "icon": "mdi:gamepad-variant-outline",
        "domains": ["roblox.com", "steampowered.com", "epicgames.com"],
        "filters": ["GAMES"],
    },
    "vpn": {
        "name": "VPN",
        "dpi": 11,
        "icon": "mdi:shield-lock-outline",
        "domains": ["nordvpn.com", "protonvpn.com", "expressvpn.com"],
        "filters": ["ANONYMIZERS"],
    },
    "messaging": {
        "name": "Messaging",
        "dpi": 0,
        "icon": "mdi:message-outline",
        "domains": ["whatsapp.com", "telegram.org", "discord.com"],
        "filters": ["INSTANT_MESSAGING"],
    },
    "adult": {
        "name": "Adult content",
        "dpi": None,
        "icon": "mdi:shield-account",
        "domains": ["pornhub.com", "xvideos.com"],
        "filters": ["ADULT", "PORNOGRAPHY"],
    },
    "gambling": {
        "name": "Gambling",
        "dpi": None,
        "icon": "mdi:cards-playing-outline",
        "domains": ["bet365.com", "pokerstars.com"],
        "filters": ["GAMBLING"],
    },
    "advertising": {
        "name": "Advertising",
        "dpi": None,
        "icon": "mdi:advertisements",
        "domains": ["doubleclick.net", "googlesyndication.com"],
        "filters": ["ADVERTISEMENT"],
    },
}
SEED_VERSION = 1
PREFIX = "builtin:"


def ensure_seeds(state):
    """Add new samples on upgrade, retaining removals and custom list identities."""
    changed = False
    for slug, category in CATEGORIES.items():
        key = PREFIX + slug
        existing = state.probes.get(key)
        if existing and existing.get("seed") != slug:
            suffix = 1
            moved = key + ":custom"
            while moved in state.probes:
                suffix += 1
                moved = key + f":custom-{suffix}"
            state.probes[moved] = state.probes.pop(key)
            if key in state.probe_results:
                state.probe_results[moved] = state.probe_results.pop(key)
            existing = None
        if existing is None:
            state.probes[key] = {
                "name": category["name"],
                "domains": sorted(category["domains"]),
                "resolver": "",
                "baseline_resolver": "",
                "group_id": None,
                "vantage": "Home Assistant host network",
                "category": slug,
                "enabled": True,
                "seed": slug,
                "seed_domains": sorted(category["domains"]),
                "removed_seed_domains": [],
                "revision": 1,
            }
            changed = True
            continue
        updated = deepcopy(existing)
        removed = set(existing.get("removed_seed_domains", []))
        updated["domains"] = sorted(set(existing["domains"]) | (set(category["domains"]) - removed))
        updated["seed_domains"] = sorted(
            set(existing.get("seed_domains", [])) | set(category["domains"])
        )
        updated["name"] = category["name"]
        updated["category"] = slug
        if updated != existing:
            updated["revision"] = existing["revision"] + 1
            state.probes[key] = updated
            state.probe_results.pop(key, None)
            changed = True
    return changed


def seed_edit(old, updated):
    if not old.get("seed"):
        return updated
    slug = old["seed"]
    if slug not in CATEGORIES:
        raise FamilyError("Unknown built-in DNS category")
    seed_domains = sorted(set(old.get("seed_domains", [])) | set(CATEGORIES[slug]["domains"]))
    return {
        **updated,
        "seed": slug,
        "category": slug,
        "name": CATEGORIES[slug]["name"],
        "seed_domains": seed_domains,
        "removed_seed_domains": sorted(set(seed_domains) - set(updated["domains"])),
    }
