"""Build a local IEEE MAC registrant snapshot; explicit maintenance, never HA startup.

IEEE's CSV export silently caps at 10,000 rows. Its public registry search has
pagination and a total count, which this importer validates before publishing.
"""

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE = "https://regauth.standards.ieee.org/standards-ra-web/rest/assignments/"


def build():
    assignments = {}
    sources = []
    for registry, length in (("MA-L", 6), ("MA-M", 7), ("MA-S", 9)):
        collected = {}
        total = None
        digest = hashlib.sha256()
        offset = 0
        while total is None or offset < total:
            body = {
                "registry": registry,
                "text": "",
                "filterType": "",
                "from": offset,
                "size": 1000,
                "sortBy": "organization",
                "sortOrder": "asc",
            }
            request = Request(
                SOURCE, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
            )
            with urlopen(request, timeout=30) as response:
                raw = response.read(16 * 1024 * 1024)
            digest.update(raw)
            page = json.loads(raw)
            if str(page.get("statusCode")) != "0":
                raise ValueError("IEEE registry read failed")
            data = page["data"]
            if total is not None and total != data["totalHits"]:
                raise ValueError("Registry changed during read; retry")
            total = data["totalHits"]
            rows = data["hits"]
            if not rows or not 1000 <= total <= 200000:
                raise ValueError("Incomplete IEEE registry")
            for row in rows:
                key = row["assignmentNumberHex"].strip().upper().zfill(length)
                name = row["organizationName"].strip()
                if len(key) != length or not name or row["requestType"] != registry:
                    raise ValueError("Invalid IEEE record")
                int(key, 16)
                collected.setdefault(key, set()).add(name)
            offset += len(rows)
        if offset != total:
            raise ValueError("Incomplete IEEE registry")
        assignments.update(
            {
                key: next(iter(names)) if len(names) == 1 else sorted(names)
                for key, names in collected.items()
            }
        )
        sources.append(
            {
                "registry": registry,
                "url": SOURCE,
                "rows": total,
                "unique_allocations": len(collected),
                "ambiguous_allocations": sum(len(names) > 1 for names in collected.values()),
                "response_sha256": digest.hexdigest(),
            }
        )
        print(registry, total, flush=True)
    metadata = {
        "source": "IEEE Registration Authority public registrant lists",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sources": sources,
    }
    root = Path(__file__).resolve().parents[1] / "custom_components/family_network/data"
    root.mkdir(exist_ok=True)
    blob = json.dumps(
        {**metadata, "assignments": assignments},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    (root / "mac-registrants.json.gz").write_bytes(gzip.compress(blob, mtime=0))
    (root / "mac-registrants-sources.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(
        {
            "entries": len(assignments),
            "compressed_bytes": (root / "mac-registrants.json.gz").stat().st_size,
        }
    )


if __name__ == "__main__":
    build()
