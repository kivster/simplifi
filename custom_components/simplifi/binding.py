"""Credential-free connection identity and durable review fingerprints."""

from .models import fingerprint
from .portable import export


def binding(data):
    return {k: data.get(k) for k in ("controller", "site", "networks", "timezone", "external_zone")}


def review_state(state):
    return fingerprint(
        {
            "configuration": export(state),
            "revision": state.revision,
            "dns_revision": state.dns_revision,
            "access_revision": state.access_revision,
            "owned": state.owned,
            "journal": state.journal,
            "management": state.management,
        }
    )
