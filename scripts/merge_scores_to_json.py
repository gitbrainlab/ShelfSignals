"""
merge_scores_to_json.py
~~~~~~~~~~~~~~~~~~~~~~~~

Merge photo likelihood scores into the main JSON data file.

Usage:
    python scripts/merge_scores_to_json.py \
        --input docs/data/sekula_index.json \
        --scores docs/data/photo_scored.jsonl \
        --output docs/data/sekula_index.json
"""

import argparse
import json


def main():
    parser = argparse.ArgumentParser(
        description="Merge photo scores into main JSON data"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input JSON file with original records",
    )
    parser.add_argument(
        "--scores",
        required=True,
        help="Input JSONL file with photo scores",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file",
    )
    args = parser.parse_args()

    # Load scores into lookup dict
    print(f"[merge] Loading scores from {args.scores}...")
    scores = {}
    with open(args.scores, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                scores[record["id"]] = {
                    "photo_insert_score": record.get("photo_insert_score"),
                    "photo_insert_bucket": record.get("photo_insert_bucket"),
                    "photo_insert_reasoning": record.get("photo_insert_reasoning"),
                }

    print(f"[merge] Loaded {len(scores)} scored records")

    # Load original records
    print(f"[merge] Loading records from {args.input}...")
    with open(args.input, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"[merge] Loaded {len(records)} records")

    # Merge scores
    matched = 0
    for record in records:
        record_id = record["id"]
        if record_id in scores:
            record.update(scores[record_id])
            matched += 1

    print(f"[merge] Merged {matched}/{len(records)} records with scores")

    # Write output
    print(f"[merge] Writing to {args.output}...")
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"[merge] Done!")


if __name__ == "__main__":
    main()
