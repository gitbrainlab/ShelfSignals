"""
photo_feature_extractor.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage 1 of the Embedded Photography Likelihood pipeline.
Generates compact, token-optimized Feature Packets from Sekula metadata.

This is a deterministic preprocessing step that extracts:
- Evidence flags (has_photographs, has_plates, etc.) via regex
- Format flags (exhibition_catalog, survey_report, etc.) via heuristics
- Domain tags from controlled vocabulary
- Page count bins, publisher normalization, call number prefix

Usage:
    python scripts/photo_feature_extractor.py \
        --input docs/data/sekula_index.json \
        --output docs/data/photo_feature_packets.jsonl
"""

import argparse
import json
import re
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Controlled vocabulary for domain tags
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS = {
    "photography": [
        r"\bphotograph",
        r"\bphoto\b",
        r"\bcamera",
        r"\bphotography\b",
        r"\bphotojournalism",
        r"\bphotographic",
    ],
    "maritime": [
        r"\bharbor",
        r"\bharbour",
        r"\bport\b",
        r"\bshipping",
        r"\bdock",
        r"\bmaritime",
        r"\bocean",
        r"\bsea\b",
        r"\bseafaring",
        r"\bnaval",
        r"\bmerchant marine",
    ],
    "labor": [
        r"\blabor",
        r"\blabour",
        r"\bworking class",
        r"\bworker",
        r"\bunion",
        r"\bstrike",
        r"\bfactory",
        r"\bindustry",
        r"\bindustrial",
    ],
    "art": [
        r"\bart\b",
        r"\bartist",
        r"\bpainting",
        r"\bsculpture",
        r"\bart photography",
    ],
    "urban": [
        r"\burban",
        r"\bcity\b",
        r"\bcities",
        r"\bmetropolitan",
        r"\binfrastructure",
        r"\blos angeles",
    ],
    "war": [
        r"\bwar",
        r"\bmilitary",
        r"\barmed forces",
        r"\bmilitarism",
        r"\bpolice",
        r"\bpolicing",
    ],
    "theory": [
        r"\bphilosophy",
        r"\btheory",
        r"\bcritical theory",
        r"\bcultural studies",
        r"\baesthetics",
    ],
    "archives": [
        r"\bmuseum",
        r"\barchive",
        r"\blibrary",
        r"\bcollecting",
        r"\bexhibition",
    ],
}


# ---------------------------------------------------------------------------
# Evidence flag extraction
# ---------------------------------------------------------------------------

def extract_evidence_flags(record: Dict) -> Dict[str, bool]:
    """Extract boolean evidence flags from metadata via regex."""
    flags = {
        "has_photographs": False,
        "has_plates": False,
        "has_illustrations": False,
        "frontispiece_only": False,
    }

    # Combine text fields for searching
    search_text = " ".join([
        record.get("title", ""),
        record.get("description", ""),
        " | ".join(record.get("notes", [])),
        " | ".join(record.get("table_of_contents", [])),
        " | ".join(record.get("formats", [])),
    ]).lower()

    # Photographs
    if re.search(r"\bphotograph(s|ic)?\b", search_text):
        flags["has_photographs"] = True

    # Plates
    if re.search(r"\bplate(s)?\b", search_text):
        flags["has_plates"] = True

    # Illustrations (but not if only frontispiece)
    if re.search(r"\billustration(s)?\b|\bill\.\b|\bfig(s|ure)?\.\b", search_text):
        flags["has_illustrations"] = True

    # Frontispiece only (reduces likelihood if no other evidence)
    if re.search(r"\bfrontispiece\b", search_text) and not flags["has_plates"]:
        flags["frontispiece_only"] = True

    return flags


# ---------------------------------------------------------------------------
# Format flag inference
# ---------------------------------------------------------------------------

def extract_format_flags(record: Dict) -> Dict[str, bool]:
    """Infer format flags from metadata heuristics."""
    flags = {
        "exhibition_catalog": False,
        "survey_report": False,
        "technical_manual": False,
        "fiction": False,
        "cookbook": False,
    }

    title = record.get("title", "").lower()
    subjects = " | ".join(record.get("subjects", [])).lower()
    notes = " | ".join(record.get("notes", [])).lower()
    material_type = record.get("material_type", "").lower()

    # Exhibition catalog
    if re.search(r"\bexhibition\b|\bcatalog\b", title) or \
       re.search(r"\bexhibition catalog", subjects):
        flags["exhibition_catalog"] = True

    # Survey report
    if re.search(r"\bsurvey\b|\breport\b|\bstatistics", title):
        flags["survey_report"] = True

    # Technical manual
    if re.search(r"\bmanual\b|\bhandbook\b|\bguide\b|\btechnical", title):
        flags["technical_manual"] = True

    # Fiction
    if "fiction" in material_type or "fiction" in subjects:
        flags["fiction"] = True

    # Cookbook
    if re.search(r"\bcookbook\b|\brecipe", title):
        flags["cookbook"] = True

    return flags


# ---------------------------------------------------------------------------
# Domain tags extraction
# ---------------------------------------------------------------------------

def extract_domain_tags(record: Dict, max_tags: int = 3) -> List[str]:
    """Extract up to max_tags domain tags from controlled vocabulary."""
    # Combine relevant text fields
    search_text = " ".join([
        record.get("title", ""),
        " | ".join(record.get("subjects", [])),
        " | ".join(record.get("notes", [])),
        record.get("description", ""),
    ]).lower()

    # Count matches per domain
    domain_scores = {}
    for domain, patterns in DOMAIN_KEYWORDS.items():
        score = 0
        for pattern in patterns:
            if re.search(pattern, search_text, re.IGNORECASE):
                score += 1
        if score > 0:
            domain_scores[domain] = score

    # Sort by score and return top N
    sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
    return [domain for domain, _ in sorted_domains[:max_tags]]


# ---------------------------------------------------------------------------
# Page count binning
# ---------------------------------------------------------------------------

def extract_page_count_bin(record: Dict) -> str:
    """Extract page count and bin it."""
    formats = record.get("formats", [])
    
    for fmt in formats:
        # Look for page counts like "250 pages" or "xvi, 345 p."
        match = re.search(r"(\d+)\s*(p\b|pages?)", fmt, re.IGNORECASE)
        if match:
            pages = int(match.group(1))
            if pages < 150:
                return "<150"
            elif pages <= 300:
                return "150-300"
            else:
                return ">300"
    
    return "unknown"


# ---------------------------------------------------------------------------
# Publisher normalization
# ---------------------------------------------------------------------------

def normalize_publisher(publishers: List[str]) -> str:
    """Normalize publisher to canonical form."""
    if not publishers:
        return ""
    
    # Take first publisher and clean it
    pub = publishers[0].strip()
    
    # Remove leading location (e.g., "New York : Morrow" -> "Morrow")
    if " : " in pub:
        pub = pub.split(" : ", 1)[1]
    
    # Remove dates
    pub = re.sub(r",?\s*\d{4}(-\d{4})?", "", pub)
    
    # Normalize common variations
    normalizations = {
        "moma": "Museum of Modern Art",
        "moma ps1": "MoMA PS1",
        "university press": "Univ. Press",
    }
    
    pub_lower = pub.lower()
    for key, value in normalizations.items():
        if key in pub_lower:
            return value
    
    return pub.strip()


# ---------------------------------------------------------------------------
# Call number prefix extraction
# ---------------------------------------------------------------------------

def extract_call_number_prefix(call_number: str) -> str:
    """Extract LC class prefix (e.g., TR, NA, HD)."""
    if not call_number:
        return ""
    
    # Extract leading letters
    match = re.match(r"^([A-Z]{1,3})", call_number)
    if match:
        return match.group(1)
    
    return ""


# ---------------------------------------------------------------------------
# Notes excerpt escalation
# ---------------------------------------------------------------------------

def extract_notes_excerpt(record: Dict, max_length: int = 240) -> str:
    """Extract notes excerpt only if trigger words present."""
    # Trigger words
    triggers = [r"\bphoto", r"\bplate", r"\bill\.", r"\bfig\."]
    
    # Combine notes fields
    all_notes = " ".join([
        record.get("description", ""),
        " | ".join(record.get("notes", [])),
        " | ".join(record.get("table_of_contents", [])),
    ])
    
    # Check for trigger words
    has_trigger = any(re.search(trigger, all_notes, re.IGNORECASE) for trigger in triggers)
    
    if not has_trigger:
        return ""
    
    # Return truncated excerpt
    if len(all_notes) <= max_length:
        return all_notes
    
    return all_notes[:max_length] + "..."


# ---------------------------------------------------------------------------
# Feature packet generation
# ---------------------------------------------------------------------------

def build_feature_packet(record: Dict) -> Dict:
    """Build a compact feature packet for a single record."""
    title = record.get("title", "")
    
    # Trim title if excessively long (>150 chars)
    if len(title) > 150:
        title = title[:147] + "..."
    
    # Extract year or decade
    year_str = record.get("year", "")
    year = None
    decade = None
    if year_str:
        # Try to extract 4-digit year
        match = re.search(r"\b(1[6-9]\d{2}|20[0-2]\d)\b", year_str)
        if match:
            year = int(match.group(1))
            decade = (year // 10) * 10
    
    packet = {
        "id": record.get("id"),
        "title": title,
        "year": year,
        "decade": decade,
        "publisher_norm": normalize_publisher(record.get("publishers", [])),
        "call_number_prefix": extract_call_number_prefix(record.get("call_number", "")),
        "domain_tags": extract_domain_tags(record, max_tags=3),
        "page_count_bin": extract_page_count_bin(record),
        "evidence_flags": extract_evidence_flags(record),
        "format_flags": extract_format_flags(record),
        "notes_excerpt": extract_notes_excerpt(record, max_length=240),
    }
    
    return packet


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract photo likelihood feature packets from Sekula metadata"
    )
    parser.add_argument(
        "--input",
        default="docs/data/sekula_index.json",
        help="Input JSON file with Sekula metadata",
    )
    parser.add_argument(
        "--output",
        default="docs/data/photo_feature_packets.jsonl",
        help="Output JSONL file with feature packets",
    )
    args = parser.parse_args()

    print(f"[photo_feature_extractor] Reading {args.input}...")
    with open(args.input, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"[photo_feature_extractor] Processing {len(records)} records...")
    packets = []
    for record in records:
        packet = build_feature_packet(record)
        packets.append(packet)

    print(f"[photo_feature_extractor] Writing {len(packets)} feature packets to {args.output}...")
    with open(args.output, "w", encoding="utf-8") as f:
        for packet in packets:
            f.write(json.dumps(packet, ensure_ascii=False) + "\n")

    print(f"[photo_feature_extractor] Done!")
    
    # Print some statistics
    with_photos = sum(1 for p in packets if p["evidence_flags"]["has_photographs"])
    with_plates = sum(1 for p in packets if p["evidence_flags"]["has_plates"])
    with_illustrations = sum(1 for p in packets if p["evidence_flags"]["has_illustrations"])
    
    print(f"\nStatistics:")
    print(f"  Records with 'photographs' flag: {with_photos} ({with_photos/len(packets)*100:.1f}%)")
    print(f"  Records with 'plates' flag: {with_plates} ({with_plates/len(packets)*100:.1f}%)")
    print(f"  Records with 'illustrations' flag: {with_illustrations} ({with_illustrations/len(packets)*100:.1f}%)")


if __name__ == "__main__":
    main()
