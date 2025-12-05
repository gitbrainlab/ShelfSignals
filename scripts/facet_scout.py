"""
facet_scout.py
~~~~~~~~~~~~~~

Probe the Primo pnxs API to understand how different filters affect the
Allan Sekula Library result counts. This helps us pick shard boundaries
that keep each slice below the 5,000-offset cap.

Usage:
    python scripts/facet_scout.py

The script prints aggregate totals for:
    - Creation date decades (pre-1940 through 2020s)
    - Call-number first characters (0-9, A-Z)
Extend the FILTER_GROUPS list to explore additional facets.
"""

from __future__ import annotations

import time
from typing import Dict, List, Sequence

import requests

BASE_URL = "https://library.clarkart.edu/primaws/rest/pub/pnxs"
BASE_Q = 'lds07,contains,"Allan Sekula Library"'
COMMON_PARAMS = {
    "vid": "01CLARKART_INST:01CLARKART_INST_FRANCINE",
    "tab": "LibraryCatalog",
    "scope": "CAI_Library",
    "inst": "01CLARKART_INST",
    "lang": "en",
    "mode": "advanced",
    "sort": "rank",
    "limit": "1",
}
HEADERS = {
    "User-Agent": "ShelfSignals-FacetScout/1.0 (+https://github.com/evcatalyst/ShelfSignals)"
}


def fetch_total(extra_facets: Sequence[str]) -> int:
    params: List[tuple] = list(COMMON_PARAMS.items())
    params.append(("q", BASE_Q))
    for facet in extra_facets:
        params.append(("multiFacets", facet))
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("info", {}).get("total", 0)


def decade_facets() -> List[Dict]:
    buckets = []
    for decade in range(1940, 2030, 10):
        start = decade
        end = decade + 9
        label = f"{decade}s"
        range_clause = f"[{start} TO {end}]"
        facet = f"facet_searchcreationdate,include,{range_clause}"
        buckets.append({"label": f"Decade:{label}", "facets": [facet]})
    return buckets


def callnumber_facets() -> List[Dict]:
    buckets: List[Dict] = []
    for digit in "0123456789":
        facet = f"facet_lds01,include,{digit}"
        buckets.append({"label": f"CallNumber:{digit}", "facets": [facet]})
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        facet = f"facet_lds01,include,{letter}"
        buckets.append({"label": f"CallNumber:{letter}", "facets": [facet]})
    buckets.append({"label": "CallNumber:Other", "facets": ["facet_lds01,include,Other"]})
    return buckets


FILTER_GROUPS = [
    ("Creation Decades", decade_facets()),
    ("Call Number Prefix", callnumber_facets()),
]


def main() -> None:
    print("Facet scout for Allan Sekula Library")
    for group_name, group in FILTER_GROUPS:
        print(f"\n=== {group_name} ===")
        for entry in group:
            label = entry["label"]
            facets = entry["facets"]
            try:
                total = fetch_total(facets)
            except requests.HTTPError as exc:
                print(f"{label:<20} ERROR {exc.response.status_code}")
                time.sleep(1.0)
                continue
            print(f"{label:<20} {total:>6}")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
