"""Check the standalone package contract without network access or HA startup."""

import gzip
import json
import re
import struct
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "family_network"


def validate():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    hacs = json.loads((ROOT / "hacs.json").read_text())
    version = manifest["version"]
    assert manifest["domain"] == "family_network"
    assert manifest["name"] == hacs["name"] == "SimpliFi"
    assert project["version"] == version
    assert re.search(
        rf'^VERSION = "{re.escape(version)}"$', (COMPONENT / "const.py").read_text(), re.M
    )
    assert (
        version in (COMPONENT / "frontend" / "family-network-card.js").read_text().splitlines()[0]
    )
    assert {
        p.name
        for p in (ROOT / "custom_components").iterdir()
        if p.is_dir() and p.name != "__pycache__"
    } == {"family_network"}
    for field in ("documentation", "issue_tracker", "codeowners", "iot_class", "integration_type"):
        assert manifest[field], field
    assert not (ROOT / "www").exists(), "Runtime card must be bundled with the integration"
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        png = (COMPONENT / "brand" / name).read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", png[16:24]) == (size, size)
    strings = json.loads((COMPONENT / "strings.json").read_text())
    assert strings == json.loads((COMPONENT / "translations" / "en.json").read_text())
    snapshot = json.loads(
        gzip.decompress((COMPONENT / "data" / "mac-registrants.json.gz").read_bytes())
    )
    assert len(snapshot["assignments"]) > 50000
    for retired in ("update_host.py", "update_source.py", "updates.py"):
        assert not (COMPONENT / retired).exists()
    print(f"SimpliFi {version}: standalone package checks passed")


if __name__ == "__main__":
    validate()
