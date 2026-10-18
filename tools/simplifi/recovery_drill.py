"""Cold-process native HA recovery drill using trusted, hash-checked release archives.

Creates its own private temporary directory. Never accepts an existing HA config.
No production credentials, controllers or Home Assistant instances are used.
"""

import argparse
import hashlib
import json
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import yaml

OWNER = {"purpose": "isolated SimpliFi restore drill", "config": "config"}
WORKER = Path(__file__).with_name("recovery_worker.py")


def release(path, checksum):
    """Validate every archive before starting executable code from either release."""
    path = path.resolve(strict=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum, "Archive SHA256 mismatch"
    with zipfile.ZipFile(path) as archive:
        assert sum(i.file_size for i in archive.infolist()) <= 20_000_000, "Archive too large"
        names = set()
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            assert (
                name.parts[:2] == ("custom_components", "simplifi")
                and ".." not in name.parts
                and "\\" not in info.filename
                and not stat.S_ISLNK(info.external_attr >> 16)
                and info.filename not in names
            ), "Unexpected archive member"
            names.add(info.filename)
        manifest = json.loads(archive.read("custom_components/simplifi/manifest.json"))
        assert manifest["domain"] == "simplifi"
    return {"path": path, "sha256": checksum, "version": manifest["version"]}


def install(root, package):
    """Replace only the simulated lab's component files, leaving HA state to HA."""
    assert json.loads((root / "lab-owner.json").read_text()) == OWNER
    config = root / "config"
    target = config / "custom_components" / "simplifi"
    assert not target.is_symlink()
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(package["path"]) as archive:
        archive.extractall(config)


def run_phase(root, phase):
    """A fresh interpreter, real disk stores, and real HA lifecycle for every phase."""
    with (root / f"{phase}-process.log").open("w") as log:
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", str(WORKER), str(root), phase],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=90,
            check=False,
        )
    output = Path(log.name).read_text()
    setup_error = re.search(r"^(?:.*\bERROR \(|ERROR:)", output, re.MULTILINE)
    if result.returncode != 0 or setup_error:
        # The fixture contains fictional data only. Never upload its auth store/archive.
        print(output[-12_000:], file=sys.stderr)
        reason = "HA startup error" if setup_error else f"exit code {result.returncode}"
        raise AssertionError(f"{phase} failed: {reason}; inspect {log.name}")
    print(f"Passed cold phase: {phase}", flush=True)
    if phase == "request-restore":
        return None
    return json.loads((root / f"{phase}-result.json").read_text())


def same_state(before, after):
    # Each cold boot adds observations and sync runs; saved intent and receipts stay exact.
    for field in (
        "controller",
        "site",
        "networks",
        "timezone",
        "schema",
        "revision",
        "confirmed_revision",
        "management",
        "expiry_acknowledged",
        "gateway_timezone_confirmed",
        "groups",
        "devices",
        "rules",
        "exceptions",
        "owned",
        "journal",
        "changes",
        "quarantine",
        "quarantine_excluded",
        "quarantine_until",
        "quarantine_suspended",
        "probes",
        "probe_results",
        "dns_revision",
        "dns_settings",
        "probe_schedule",
        "audit_days",
        "access_revision",
        "access_grants",
        "binding_token",
    ):
        assert before["state"][field] == after["state"][field], f"State changed: {field}"
    for field in ("entry", "entry_data", "export", "gateway", "entities", "users"):
        assert before[field] == after[field], f"Identity/configuration changed: {field}"
    for field in ("dashboards", "household", "unrelated"):
        assert before["ui"][field] == after["ui"][field], f"Dashboard changed: {field}"
    older = {i["id"]: i for i in before["history"]["items"]}
    newer = {i["id"]: i for i in after["history"]["items"]}
    assert all(newer.get(key) == value for key, value in older.items()), "History lost or rewritten"
    previous_resources = {r["id"]: r for r in before["ui"]["resources"]}
    current_resources = {r["id"]: r for r in after["ui"]["resources"]}
    assert previous_resources.keys() == current_resources.keys(), "Resource identity changed"
    for key, item in current_resources.items():
        expected = dict(previous_resources[key])
        if expected["url"].startswith("/simplifi_static/simplifi-card.js?v="):
            expected["url"] = f"/simplifi_static/simplifi-card.js?v={after['version']}"
        assert item == expected, "Unrelated resource changed or stale SimpliFi resource"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-archive", type=Path, required=True)
    parser.add_argument("--previous-sha256", required=True)
    parser.add_argument("--current-archive", type=Path, required=True)
    parser.add_argument("--current-sha256", required=True)
    args = parser.parse_args()
    if sys.flags.optimize:
        raise RuntimeError("Run without -O; assertions are acceptance checks")
    previous = release(args.previous_archive, args.previous_sha256)
    current = release(args.current_archive, args.current_sha256)
    root = Path(tempfile.mkdtemp(prefix="simplifi-recovery-lab-")).resolve()
    root.chmod(0o700)
    (root / "lab-owner.json").write_text(json.dumps(OWNER))
    (root / "config").mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    (root / "config" / "configuration.yaml").write_text(
        yaml.safe_dump(
            {
                "homeassistant": {
                    "name": "SimpliFi recovery lab",
                    "latitude": 0,
                    "longitude": 0,
                    "elevation": 0,
                    "country": "GB",
                    "time_zone": "Europe/London",
                    "unit_system": "metric",
                },
                "http": {"server_host": "127.0.0.1", "server_port": port},
                "frontend": {},
                "api": {},
                "backup": {},
                "lovelace": {"mode": "storage"},
                "logger": {"default": "warning"},
            }
        )
    )
    print(f"Private fictional fixture and logs: {root}", flush=True)
    install(root, previous)
    seeded = run_phase(root, "seed")
    cold = run_phase(root, "cold-old")
    same_state(seeded, cold)
    install(root, current)
    upgraded = run_phase(root, "upgrade")
    assert upgraded["version"] == current["version"]
    same_state(cold, upgraded)
    controls = run_phase(root, "new-controls")
    assert {e["kind"] for e in controls["state"]["exceptions"].values()} == {
        "pause",
        "internet_allow",
    }
    backed_up = run_phase(root, "backup")
    same_state(controls, backed_up)
    changed = run_phase(root, "change-after-backup")
    assert changed["state"]["groups"]["demo-family"]["name"] == "Changed after backup"
    assert changed["gateway"] == backed_up["gateway"]
    run_phase(root, "request-restore")
    restored = run_phase(root, "restored")
    # Backup precedes its own final observation; compare with the prior cold process.
    same_state(controls, restored)
    assert restored["state"]["groups"]["demo-family"]["name"] == "Lab household"
    assert not (root / "config" / ".HA_RESTORE").exists()
    retried = run_phase(root, "retry-after-restore")
    same_state(restored, retried)
    install(root, previous)
    rolled_back = run_phase(root, "rollback")
    assert rolled_back["version"] == previous["version"]
    same_state(retried, rolled_back)
    install(root, current)
    reupgraded = run_phase(root, "reupgrade")
    same_state(rolled_back, reupgraded)
    report = {
        "passed": True,
        "homeassistant": __import__("homeassistant.const", fromlist=["__version__"]).__version__,
        "python": sys.version.split()[0],
        "releases": [{k: p[k] for k in ("version", "sha256")} for p in (previous, current)],
        "checks": [
            "cold persistence",
            "update",
            "native Core backup/restore",
            "manual pause and allowance coexistence",
            "retained request retry",
            "release rollback and reupgrade",
            "entry and entity identity",
            "HA users and access grants",
            "assignments and rules",
            "ownership and journal",
            "history retention",
            "customized and unrelated dashboards",
            "versioned resource identity",
            "served card bytes match the selected release",
            "no duplicate simulated policy creation",
        ],
        "limits": [
            "simulated gateway",
            "Home Assistant Core only",
            "no recorder database",
            "trusted release files installed directly; HACS UI was not exercised",
            "no physical clients, Companion/Watch, HAOS, Supervisor or App restore",
        ],
    }
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
