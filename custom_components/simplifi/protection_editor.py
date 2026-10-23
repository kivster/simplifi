"""Explicit administrator edits of existing UniFi content-filter profiles.

The local v2 API is compatibility-sensitive. Preserve scope, schedule and unknown
fields; never adopt these profiles into the policy reconciler. An uncertain write
is journalled before I/O and must be resolved by readback before another edit.
"""

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import uuid4

from aiounifi.models.api import ApiRequest, ApiRequestV2
from homeassistant.helpers.storage import Store

from .metered_unifi import read
from .models import SimpliFiError, domain_name, instant
from .protection import normalize_profiles

FIELDS = ("enabled", "categories", "safe_search", "allow_list", "block_list")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def editable(row):
    return {k: deepcopy(row[k]) for k in FIELDS}


def validated(changes, row, catalogue):
    if set(changes) != set(FIELDS) or type(changes.get("enabled")) is not bool:
        raise SimpliFiError("Provide enabled, categories, SafeSearch and both domain lists")
    result = deepcopy(changes)
    for key in FIELDS[1:]:
        values = result[key]
        if (
            not isinstance(values, list)
            or len(values) > 10000
            or any(not isinstance(v, str) for v in values)
        ):
            raise SimpliFiError("Invalid or oversized filtering list")
        if len(set(values)) != len(values):
            raise SimpliFiError("Remove duplicate entries before reviewing")
    if set(result["categories"]) - (catalogue | set(row["categories"])):
        raise SimpliFiError("Select categories observed on this controller")
    if set(result["safe_search"]) - ({"GOOGLE", "BING", "YOUTUBE"} | set(row["safe_search"])):
        raise SimpliFiError("Unknown SafeSearch provider")
    for key in ("allow_list", "block_list"):
        # Preserve existing controller entries (including legacy IP entries).
        result[key] = [v if v in row[key] else domain_name(v) for v in result[key]]
        if len(set(result[key])) != len(result[key]):
            raise SimpliFiError("Duplicate normalized domains")
    if set(result["allow_list"]) & set(result["block_list"]):
        raise SimpliFiError("A domain cannot be both allowed and blocked")
    return result


class ProtectionEditor:
    def __init__(self, hass, entry_id, reader, engine):
        self.reader, self.engine = reader, engine
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"simplifi.{entry_id}.profile_edit")
        self.lock = asyncio.Lock()
        self.previews = {}

    async def status(self):
        journal = await self.store.async_load()
        return (
            {k: journal[k] for k in ("status", "at", "profile_id", "before", "after")}
            if journal
            else None
        )

    async def _read(self):
        api = self.reader._source()
        async with asyncio.timeout(15):
            filters = await read(
                api, ApiRequestV2(method="get", path="/content-filtering"), self.reader.gateway
            )
            networks = await read(
                api, ApiRequest(method="get", path="/rest/networkconf"), self.reader.gateway
            )
        profiles = normalize_profiles(filters, networks, self.reader.gateway.networks)
        rows = filters.get("data") if isinstance(filters, dict) else filters
        if not isinstance(rows, list):
            raise SimpliFiError("Incomplete profile collection")
        return api, {r["_id"]: r for r in rows}, profiles

    def _gate(self):
        if self.engine.gateway.simulation:
            raise SimpliFiError("Profile editing requires a connected UniFi controller")
        if not self.engine.state.management:
            raise SimpliFiError("Enable management before editing a UniFi profile")

    async def preview(self, profile_id, changes, actor):
        async with self.lock:
            self._gate()
            try:
                _, rows, profiles = await self._read()
            except Exception:
                raise SimpliFiError(
                    "Cannot read current UniFi profiles; no change was sent"
                ) from None
            journal = await self.store.async_load()
            if journal and journal["status"] == "uncertain":
                current = rows.get(journal["profile_id"])
                if current is None or digest(current) not in {
                    journal["before_hash"],
                    journal["after_hash"],
                }:
                    raise SimpliFiError(
                        "Previous profile edit is uncertain. Review the profile in UniFi before continuing"
                    )
                journal["status"] = (
                    "confirmed" if digest(current) == journal["after_hash"] else "not_applied"
                )
                await self.store.async_save(journal)
            row = rows.get(profile_id)
            if row is None or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", profile_id):
                raise SimpliFiError("Select an existing profile")
            catalogue = {c for r in rows.values() for c in r["categories"]}
            desired = validated(changes, row, catalogue)
            now = self.engine.clock()
            self.previews = {k: v for k, v in self.previews.items() if v["expires"] > now}
            if len(self.previews) >= 20:
                raise SimpliFiError("Too many pending reviews; wait five minutes")
            token = str(uuid4())
            self.previews[token] = {
                "actor": actor,
                "expires": now + timedelta(minutes=5),
                "row": deepcopy(row),
                "changes": desired,
            }
            profile = next(p for p in profiles if p["id"] == profile_id)
            return {
                "preview_token": token,
                "profile": profile,
                "before": editable(row),
                "after": desired,
                "changed_fields": [k for k in FIELDS if row[k] != desired[k]],
                "note": "Applies to every listed network and individual device, including devices outside SimpliFi. Scope and schedule stay as shown.",
            }

    async def apply(self, token, actor, confirm, deadline):
        async with self.lock:
            self._gate()
            now = self.engine.clock()
            if (
                not confirm
                or not deadline
                or not now < instant(deadline) <= now + timedelta(minutes=5)
            ):
                raise SimpliFiError("Confirm a fresh review before saving")
            preview = self.previews.get(token)
            if not preview or preview["actor"] != actor or preview["expires"] <= now:
                raise SimpliFiError(
                    "Review expired or belongs to another administrator; review again"
                )
            journal = await self.store.async_load()
            if journal and journal["status"] == "uncertain":
                raise SimpliFiError("Previous profile edit needs readback; open a fresh review")
            try:
                api, rows, _ = await self._read()
            except Exception:
                raise SimpliFiError("Cannot recheck UniFi profile; no change was sent") from None
            original = preview["row"]
            if rows.get(original["_id"]) != original:
                self.previews.pop(token)
                raise SimpliFiError(
                    "Profile changed in UniFi since review. Reopen it and review again"
                )
            updated = {**deepcopy(original), **preview["changes"]}
            if updated == original:
                self.previews.pop(token)
                return {"status": "unchanged", "message": "Profile already matches; no write sent"}
            journal = {
                "status": "uncertain",
                "at": now.isoformat(),
                "actor": actor,
                "profile_id": original["_id"],
                "before": editable(original),
                "after": editable(updated),
                "before_hash": digest(original),
                "after_hash": digest(updated),
            }
            self._gate()
            await self.store.async_save(journal)
            self.previews.pop(token)
            try:
                async with asyncio.timeout(15):
                    await read(
                        api,
                        ApiRequestV2(
                            method="put", path=f"/content-filtering/{original['_id']}", data=updated
                        ),
                        self.reader.gateway,
                    )
                _, observed, profiles = await self._read()
                if observed.get(original["_id"]) != updated:
                    raise SimpliFiError("Readback differs")
            except Exception:
                self.reader.error = "Profile save could not be confirmed; inspect UniFi and reopen the editor before retrying"
                raise SimpliFiError(self.reader.error) from None
            journal["status"] = "confirmed"
            await self.store.async_save(journal)
            self.reader.profiles = profiles
            self.reader.last_success = self.engine.clock()
            self.reader.last_attempt = self.reader.last_success
            self.reader.error = None
            return {
                "status": "confirmed",
                "message": "UniFi profile saved and read back. Device traffic has not been tested.",
            }
