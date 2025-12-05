"""
sekula_indexer.py
~~~~~~~~~~~~~~~~~

Local indexer for Allan Sekula Library holdings in the Clark Art Institute
catalog. The script talks directly to the Primo VE JSON API (pnxs) so no
Selenium/browser automation is required.

Requirements:

    pip install requests
"""

from __future__ import annotations

import csv
import json
import os
import random
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

import requests
from requests import Response


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://library.clarkart.edu/primaws/rest/pub/pnxs"
VID = "01CLARKART_INST:01CLARKART_INST_FRANCINE"
TAB = "LibraryCatalog"
SCOPE = "CAI_Library"
INSTITUTION = "01CLARKART_INST"
COLLECTION_NAME = "Allan Sekula Library"

LIMIT = 50  # How many results to request per API call
DELAY_SEC = 1.2  # Base delay between page fetches
JITTER_SEC = 0.8  # Random jitter to avoid a fixed cadence
RETRY_LIMIT = 3
CHECKPOINT_PAGES = 5  # Write outputs during a shard
RATE_LIMIT_BASE = 60  # Base wait (seconds) after a 403
RATE_LIMIT_MAX = 900  # Cap wait after repeated 403s (15 minutes)

JSON_OUTPUT = "sekula_index.json"
CSV_OUTPUT = "sekula_index.csv"

SHARDS = [
    {"label": "Pre1940", "facet": "[1800 TO 1939]"},
]
for decade in range(1940, 2030, 10):
    SHARDS.append({"label": f"{decade}s", "facet": f"[{decade} TO {decade + 9}]"})

START_SHARD = 0  # Set >0 to skip shards that already ran

HEADERS = {
    "User-Agent": "ShelfSignals-Sekula-Indexer/1.0 (+https://github.com/evcatalyst/ShelfSignals)"
}

# Base parameters shared by every pnxs request.
PARAMS_BASE = {
    "vid": VID,
    "tab": TAB,
    "scope": SCOPE,
    "inst": INSTITUTION,
    "lang": "en",
    "mode": "advanced",
    "sort": "rank",
    # Search within the custom field (lds07) that marks Sekula holdings.
    "q": 'lds07,contains,"Allan Sekula Library"',
}


# ---------------------------------------------------------------------------
# Fetching helpers
# ---------------------------------------------------------------------------

def fetch_page(offset: int, facet_range: str, limit: int = LIMIT) -> Dict:
    """Fetch one page of Primo JSON results."""
    params = dict(PARAMS_BASE)
    params["offset"] = str(offset)
    params["limit"] = str(limit)
    params["came_from"] = "addFacet"
    params["multiFacets"] = f"facet_searchcreationdate,include,{facet_range}"

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            resp: Response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=(10, 60))
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            print(f"[fetch_page] Attempt {attempt}/{RETRY_LIMIT} failed: {exc}")
            if attempt == RETRY_LIMIT:
                raise
            time.sleep(DELAY_SEC * attempt)

    raise RuntimeError("Unreachable code in fetch_page")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def normalize_list(value: Optional[List[str]]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value if item and item.strip()]


def strip_marc_subfields(text: str) -> str:
    if "$$" not in text:
        return text
    return text.split("$$", 1)[0].strip()


def clean_values(value: Optional[List[str]]) -> List[str]:
    return [strip_marc_subfields(item) for item in normalize_list(value)]


def first_value(value: Optional[List[str]]) -> str:
    items = clean_values(value)
    return items[0] if items else ""


def slim_location(location: Optional[Dict]) -> Dict:
    if not location:
        return {}
    keep_keys = [
        "organization",
        "libraryCode",
        "mainLocation",
        "subLocation",
        "subLocationCode",
        "callNumber",
        "callNumberType",
        "availabilityStatus",
        "holKey",
    ]
    return {key: location.get(key) for key in keep_keys if key in location}


def slim_holdings(holdings: Optional[List[Dict]]) -> List[Dict]:
    if not holdings:
        return []
    return [slim_location(holding) for holding in holdings]


def build_record(doc: Dict) -> Optional[Dict]:
    """Map a Primo doc entry into our output schema."""
    pnx = doc.get("pnx", {})
    display = pnx.get("display", {})
    control = pnx.get("control", {})
    delivery = doc.get("delivery", {})
    addata = pnx.get("addata", {})
    facets = pnx.get("facets", {})

    collections = clean_values(display.get("lds07"))
    if not any(COLLECTION_NAME.lower() in c.lower() for c in collections):
        return None

    record_id = clean_values(control.get("recordid"))
    if not record_id:
        return None
    docid = record_id[0]

    title = first_value(display.get("title"))
    uniform_title = first_value(display.get("unititle"))
    alternative_titles = clean_values(display.get("addtitle") or addata.get("addtitle"))
    authors = clean_values(display.get("creator")) or clean_values(addata.get("au"))
    contributors = clean_values(display.get("contributor"))
    year = first_value(display.get("creationdate") or addata.get("date"))
    subjects = clean_values(display.get("subject"))
    languages = clean_values(display.get("language"))
    material_type = first_value(display.get("type"))
    formats = clean_values(display.get("format"))
    identifiers = clean_values(display.get("identifier"))
    publishers = clean_values(display.get("publisher") or addata.get("pub"))
    places = clean_values(display.get("place") or addata.get("cop"))
    series = clean_values(display.get("series"))
    table_of_contents = clean_values(display.get("contents") or display.get("lds16"))
    description_text = " ".join(clean_values(display.get("description")))
    provenance_notes = clean_values(display.get("lds14"))
    sekula_notes = clean_values(display.get("lds23"))
    call_number_notes = clean_values(display.get("lds01"))
    notes = clean_values(addata.get("notes"))
    best_location = slim_location(delivery.get("bestlocation"))
    holdings = slim_holdings(delivery.get("holding"))

    call_number = best_location.get("callNumber") or (call_number_notes[0] if call_number_notes else "")

    record = {
        "id": docid,
        "alma_mms": first_value(display.get("mms")),
        "source_record_id": first_value(control.get("sourcerecordid")),
        "original_source_id": first_value(control.get("originalsourceid")),
        "source_system": first_value(control.get("sourcesystem")),
        "frbr_group_id": first_value(facets.get("frbrgroupid")),
        "title": title,
        "uniform_title": uniform_title,
        "alternative_titles": alternative_titles,
        "authors": authors,
        "contributors": contributors,
        "year": year,
        "languages": languages,
        "material_type": material_type,
        "formats": formats,
        "identifiers": identifiers,
        "publishers": publishers,
        "places": places,
        "series": series,
        "table_of_contents": table_of_contents,
        "description": description_text,
        "notes": notes,
        "provenance_notes": provenance_notes,
        "sekula_notes": sekula_notes,
        "subjects": subjects,
        "collection": COLLECTION_NAME,
        "collection_tags": collections,
        "call_number": call_number,
        "call_number_notes": call_number_notes,
        "availability": best_location.get("availabilityStatus"),
        "best_location": best_location,
        "holdings": holdings,
        "isbns": clean_values(addata.get("isbn")),
        "issns": clean_values(addata.get("issn")),
        "oclc_numbers": clean_values(addata.get("oclcid")),
        "lccn": clean_values(addata.get("lccn")),
        "record_url": build_record_url(docid),
        "source": "Clark Library Catalog",
    }

    return record


def build_record_url(docid: str) -> str:
    params = {
        "docid": docid,
        "context": "L",
        "vid": VID,
        "lang": "en",
        "tab": TAB,
    }
    query = urlencode(params)
    return f"https://library.clarkart.edu/discovery/fulldisplay?{query}"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

LIST_FIELDS = [
    "authors",
    "contributors",
    "subjects",
    "languages",
    "formats",
    "identifiers",
    "publishers",
    "places",
    "series",
    "table_of_contents",
    "notes",
    "provenance_notes",
    "sekula_notes",
    "call_number_notes",
    "isbns",
    "issns",
    "oclc_numbers",
    "lccn",
    "alternative_titles",
    "collection_tags",
]

JSON_FIELDS = ["best_location", "holdings"]


def write_outputs(records: List[Dict]) -> None:
    json_tmp = f"{JSON_OUTPUT}.tmp"
    with open(json_tmp, "w", encoding="utf-8") as f_json:
        json.dump(records, f_json, indent=2, ensure_ascii=False)
    os.replace(json_tmp, JSON_OUTPUT)

    fieldnames = [
        "id",
        "alma_mms",
        "source_record_id",
        "original_source_id",
        "source_system",
        "frbr_group_id",
        "title",
        "uniform_title",
        "alternative_titles",
        "authors",
        "contributors",
        "year",
        "languages",
        "material_type",
        "formats",
        "identifiers",
        "publishers",
        "places",
        "series",
        "table_of_contents",
        "description",
        "notes",
        "provenance_notes",
        "sekula_notes",
        "subjects",
        "collection",
        "collection_tags",
        "call_number",
        "call_number_notes",
        "availability",
        "best_location",
        "holdings",
        "isbns",
        "issns",
        "oclc_numbers",
        "lccn",
        "record_url",
        "source",
    ]
    csv_tmp = f"{CSV_OUTPUT}.tmp"
    with open(csv_tmp, "w", encoding="utf-8", newline="") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = dict(rec)
            for key in LIST_FIELDS:
                row[key] = " | ".join(rec.get(key, []))
            for key in JSON_FIELDS:
                row[key] = json.dumps(rec.get(key), ensure_ascii=False)
            writer.writerow(row)
    os.replace(csv_tmp, CSV_OUTPUT)


def checkpoint(records: List[Dict], label: str) -> None:
    write_outputs(records)
    print(f"[main] Checkpoint ({label}): persisted {len(records)} records.")


# ---------------------------------------------------------------------------
# Main crawl loop
# ---------------------------------------------------------------------------

def crawl_shard(facet_label: str, facet_range: str, records: List[Dict], seen_ids: set) -> None:
    print(f"[main] === Shard {facet_label} ({facet_range}) ===")
    offset = 0
    page_index = 0
    total_results: Optional[int] = None
    consecutive_empty = 0
    consecutive_errors = 0
    rate_limit_hits = 0

    while True:
        print(f"[main] Fetching page {page_index + 1} (offset={offset})")
        try:
            data = fetch_page(offset, facet_range)
            consecutive_errors = 0
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            consecutive_errors += 1
            if status == 403:
                rate_limit_hits += 1
                wait = min(RATE_LIMIT_MAX, RATE_LIMIT_BASE * rate_limit_hits)
                print(
                    f"[main] Received 403 (possible rate limit). Waiting {wait:.2f}s before retry "
                    f"(hit {rate_limit_hits})."
                )
                time.sleep(wait)
                continue
            if consecutive_errors > RETRY_LIMIT:
                print(f"[main] Fatal HTTP error after {consecutive_errors} consecutive failures: {exc}")
                checkpoint(records, f"{facet_label} http-error failure")
                raise
            wait = min(90, DELAY_SEC * (consecutive_errors + 1))
            print(f"[main] HTTP error ({exc}); retrying offset {offset} after {wait:.2f}s "
                  f"(attempt {consecutive_errors}/{RETRY_LIMIT})")
            time.sleep(wait)
            continue
        except requests.RequestException as exc:
            consecutive_errors += 1
            if consecutive_errors > RETRY_LIMIT:
                print(f"[main] Fatal request error after {consecutive_errors} consecutive failures: {exc}")
                checkpoint(records, f"{facet_label} request failure")
                raise
            wait = min(90, DELAY_SEC * (consecutive_errors + 1))
            print(f"[main] Request error ({exc}); retrying offset {offset} after {wait:.2f}s "
                  f"(attempt {consecutive_errors}/{RETRY_LIMIT})")
            time.sleep(wait)
            continue

        docs = data.get("docs", [])
        if total_results is None:
            total_results = data.get("info", {}).get("total")
            if total_results is not None:
                print(f"[main] Reported total results for {facet_label}: {total_results}")

        if not docs:
            if total_results is not None and offset < total_results and consecutive_empty < RETRY_LIMIT:
                consecutive_empty += 1
                wait = (DELAY_SEC + 1) * (consecutive_empty + 1)
                print(f"[main] Empty page before reaching total; retrying offset {offset} after {wait:.2f}s "
                      f"(attempt {consecutive_empty}/{RETRY_LIMIT})")
                time.sleep(wait)
                continue

            print(f"[main] No docs returned for shard {facet_label}, stopping shard.")
            break

        consecutive_empty = 0

        page_records = []
        for doc in docs:
            record = build_record(doc)
            if record:
                record_id = record.get("id")
                if record_id and record_id in seen_ids:
                    continue
                if record_id:
                    seen_ids.add(record_id)
                page_records.append(record)
                records.append(record)

        print(f"[main] Page yielded {len(page_records)} Sekula records (running total: {len(records)})")

        if page_index % CHECKPOINT_PAGES == 0 and page_index > 0:
            checkpoint(records, f"{facet_label} page {page_index}")

        increment = len(docs) or LIMIT
        offset += increment
        page_index += 1
        time.sleep(DELAY_SEC + random.uniform(0, JITTER_SEC))

        if total_results is not None and offset >= total_results:
            print(f"[main] Reached reported total results for shard {facet_label}, stopping shard.")
            break


def main() -> None:
    records: List[Dict] = []
    seen_ids = set()

    print("[main] Starting Sekula indexer (pnxs API mode, sharded by decade).")

    for index, shard in enumerate(SHARDS):
        if index < START_SHARD:
            print(f"[main] Skipping shard {shard['label']} (index {index}) per START_SHARD.")
            continue
        try:
            crawl_shard(shard["label"], shard["facet"], records, seen_ids)
        except KeyboardInterrupt:
            print("[main] Crawl interrupted; writing checkpoint and exiting.")
            checkpoint(records, f"{shard['label']} interrupt")
            return
        checkpoint(records, f"{shard['label']} complete")

    print(f"[main] Finished crawl. Total Sekula records: {len(records)}")
    checkpoint(records, "complete")
    print(f"[main] Wrote JSON to {JSON_OUTPUT} and CSV to {CSV_OUTPUT}")


if __name__ == "__main__":
    main()
