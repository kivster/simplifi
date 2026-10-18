"""Integration constants."""

DOMAIN = "family_network"
VERSION = "0.18.0b1"
SCHEMA_VERSION = 1
PLATFORMS = ["sensor", "binary_sensor", "switch", "calendar"]
MAX_DURATION_MINUTES = 10080
MAX_POLICIES = 256
STALE_SECONDS = 90

CARD_URL = "/family_network_static/family-network-card.js"
CARD_RESOURCE = f"{CARD_URL}?v={VERSION}"
