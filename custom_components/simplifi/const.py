"""Integration constants."""

DOMAIN = "simplifi"
VERSION = "0.20.1b1"
SCHEMA_VERSION = 1
PLATFORMS = ["sensor", "binary_sensor", "switch", "calendar"]
MAX_DURATION_MINUTES = 10080
MAX_POLICIES = 256
STALE_SECONDS = 90

CARD_URL = "/simplifi_static/simplifi-card.js"
CARD_RESOURCE = f"{CARD_URL}?v={VERSION}"
