# MAC registrant observations

`mac-registrants.json.gz` contains public IEEE MA-L, MA-M and MA-S allocation facts obtained directly from the [IEEE Registration Authority](https://regauth.standards.ieee.org/standards-ra-web/pub/view.html). Addresses/contact details are discarded. The adjacent source manifest records retrieval time, counts and hashes of the paginated source responses.

`python scripts/update_family_network_registrants.py` explicitly refreshes the snapshot. The public CSV export is capped at 10,000 rows; the script instead reads the public search API with count validation. Duplicate historical allocations with different registrants are retained as ambiguous; the integration does not identify them. Longest allocation prefix wins. Local/private MACs are never given a registrant.

Home Assistant reads this bundled file once in an executor. It makes no external registrant requests and sends no household MAC addresses to IEEE. A registrant is not a verified manufacturer, model, person or ownership claim. Missing/failed lookup and stale observations remain explicit.

See the repository's `THIRD_PARTY_NOTICES.md` for source attribution and the distinction between project code and registry facts.
