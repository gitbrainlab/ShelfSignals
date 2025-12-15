"""
photo_likelihood_scorer.py
~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage 2 of the Embedded Photography Likelihood pipeline.
Scores feature packets using the xAI (Grok) API to estimate likelihood
that books contain embedded photographic inserts or plates.

Usage:
    python scripts/photo_likelihood_scorer.py \
        --input docs/data/photo_feature_packets.jsonl \
        --output docs/data/photo_scored.jsonl \
        --api-key $XAI_API_KEY

Environment:
    XAI_API_KEY: xAI API key (can also be passed via --api-key)
"""

import argparse
import json
import os
import time
from typing import Dict, List, Optional
import sys

try:
    import requests
except ImportError:
    print("Error: requests library not found. Install with: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROMPT_VERSION = "v1.0"
MODEL_NAME = "grok-beta"
PROVIDER = "xAI"
XAI_API_URL = "https://api.x.ai/v1/chat/completions"

CHUNK_SIZE = 100  # Process this many records per API call
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds
RETRY_MAX_DELAY = 60.0  # seconds


# ---------------------------------------------------------------------------
# Frozen v1 Scoring Prompt
# ---------------------------------------------------------------------------

SCORING_PROMPT_TEMPLATE = """You are a library metadata analyst specializing in photographic content detection. Your task is to estimate the likelihood (0-100) that a book matching the provided metadata contains actual photographic inserts or plates, even when not categorized as a photography book.

**Core Constraints (non-negotiable):**
- This is a probabilistic prior, not a claim about a specific physical copy
- Do not infer certainty unless explicit evidence flags exist
- Do not treat drawings, diagrams, maps, engravings, or artistic reproductions as photographs unless explicitly photographic
- Output must be conservative and suitable for aggregation

**Scoring Guidelines:**

**Score >70 (Strongly Likely)** - Multiple converging signals:
- Evidence flags explicitly mention photographs/plates AND
- Domain tags include photography/visual arts AND
- Publication format typical for photographic content (e.g., exhibition catalogs, photo surveys)

**Score 55-74 (Likely)** - Strong single signal or moderate convergence:
- Evidence flags mention photographs/plates OR
- Domain photography + exhibition catalog OR
- Technical manual in visual/photographic domain with illustrations

**Score 35-54 (Plausible)** - Weak signals or disciplinary norms:
- Illustrations flag + domain tags suggest visual content (art, urban, maritime)
- Survey reports or technical manuals in domains that sometimes use photos
- Decades where photography was emerging (1940s-1960s) with visual domain tags

**Score <35 (Unlikely)** - Default conservative stance:
- No evidence flags
- Non-visual domains (fiction, theory, cookbooks)
- Format flags suggest text-only content

**Book Metadata:**
{metadata_json}

**Required Output Format (JSON):**
{{
  "likelihood": <integer 0-100>,
  "reasoning": "<2-4 short sentences explaining the score, normative not edition-specific>"
}}

Respond with ONLY the JSON object, no additional text."""


# ---------------------------------------------------------------------------
# Score to Bucket Mapping
# ---------------------------------------------------------------------------

def score_to_bucket(score: int) -> str:
    """Map score to descriptive bucket."""
    if score >= 75:
        return "Strongly Likely"
    elif score >= 55:
        return "Likely"
    elif score >= 35:
        return "Plausible"
    else:
        return "Unlikely"


# ---------------------------------------------------------------------------
# API Interaction
# ---------------------------------------------------------------------------

def call_grok_api(
    packets: List[Dict],
    api_key: str,
    mock: bool = False
) -> List[Dict]:
    """
    Call Grok API to score a batch of feature packets.
    
    Args:
        packets: List of feature packets to score
        api_key: xAI API key
        mock: If True, return mock responses instead of calling API
    
    Returns:
        List of scoring results with likelihood, reasoning, and metadata
    """
    if mock:
        return mock_grok_responses(packets)
    
    results = []
    
    for packet in packets:
        # Build prompt with this packet's metadata
        metadata_json = json.dumps(packet, indent=2)
        prompt = SCORING_PROMPT_TEMPLATE.format(metadata_json=metadata_json)
        
        # Call API with retries
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    XAI_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL_NAME,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a precise library metadata analyst. Always respond with valid JSON only."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.3,  # Low temperature for consistency
                    },
                    timeout=30,
                )
                response.raise_for_status()
                
                # Parse response
                api_result = response.json()
                content = api_result["choices"][0]["message"]["content"].strip()
                
                # Extract JSON from response (may have markdown code blocks)
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                scoring = json.loads(content)
                
                # Validate response
                if "likelihood" not in scoring or "reasoning" not in scoring:
                    raise ValueError(f"Invalid response format: {scoring}")
                
                results.append({
                    "id": packet["id"],
                    "likelihood": int(scoring["likelihood"]),
                    "reasoning": scoring["reasoning"],
                })
                
                # Success, break retry loop
                break
                
            except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError) as exc:
                if attempt < MAX_RETRIES - 1:
                    delay = min(RETRY_MAX_DELAY, RETRY_BASE_DELAY * (2 ** attempt))
                    print(f"  [scorer] Error scoring {packet['id']}: {exc}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    # Final attempt failed, use conservative fallback
                    print(f"  [scorer] Failed to score {packet['id']} after {MAX_RETRIES} attempts: {exc}")
                    results.append({
                        "id": packet["id"],
                        "likelihood": 20,  # Conservative fallback
                        "reasoning": "Unable to score due to API error; conservative default applied.",
                    })
        
        # Small delay between requests to be respectful
        time.sleep(0.5)
    
    return results


def mock_grok_responses(packets: List[Dict]) -> List[Dict]:
    """
    Generate mock responses for testing without API calls.
    Uses simple heuristics based on evidence flags.
    """
    results = []
    
    for packet in packets:
        evidence = packet.get("evidence_flags", {})
        format_flags = packet.get("format_flags", {})
        domain_tags = packet.get("domain_tags", [])
        
        # Simple heuristic scoring
        if evidence.get("has_photographs") and "photography" in domain_tags:
            likelihood = 85
            reasoning = "Mock: Explicit photograph evidence with photography domain tag suggests strong likelihood."
        elif evidence.get("has_plates") or evidence.get("has_photographs"):
            likelihood = 70
            reasoning = "Mock: Evidence flags indicate plates or photographs present."
        elif format_flags.get("exhibition_catalog") and "photography" in domain_tags:
            likelihood = 65
            reasoning = "Mock: Exhibition catalog in photography domain likely contains photographic plates."
        elif evidence.get("has_illustrations") and any(tag in domain_tags for tag in ["photography", "art", "urban"]):
            likelihood = 45
            reasoning = "Mock: Illustrations in visual domain may include some photographic content."
        elif format_flags.get("fiction"):
            likelihood = 15
            reasoning = "Mock: Fiction works rarely contain photographic inserts."
        else:
            likelihood = 25
            reasoning = "Mock: Conservative default with no strong evidence."
        
        results.append({
            "id": packet["id"],
            "likelihood": likelihood,
            "reasoning": reasoning,
        })
    
    return results


# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------

def load_checkpoint(output_path: str) -> Dict[str, Dict]:
    """Load already-scored records from checkpoint file."""
    checkpoint = {}
    
    if not os.path.exists(output_path):
        return checkpoint
    
    print(f"[scorer] Loading checkpoint from {output_path}...")
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                checkpoint[record["id"]] = record
    
    print(f"[scorer] Loaded {len(checkpoint)} already-scored records")
    return checkpoint


def save_checkpoint(records: List[Dict], output_path: str) -> None:
    """Save scored records to checkpoint file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main Scoring Pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Score photo likelihood using Grok API"
    )
    parser.add_argument(
        "--input",
        default="docs/data/photo_feature_packets.jsonl",
        help="Input JSONL file with feature packets",
    )
    parser.add_argument(
        "--output",
        default="docs/data/photo_scored.jsonl",
        help="Output JSONL file with scores",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("XAI_API_KEY"),
        help="xAI API key (default: $XAI_API_KEY)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock responses instead of API calls (for testing)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Number of records per chunk (default: {CHUNK_SIZE})",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier for tracking",
    )
    args = parser.parse_args()

    if not args.mock and not args.api_key:
        print("Error: --api-key required (or set $XAI_API_KEY environment variable)")
        print("Use --mock for testing without API access")
        sys.exit(1)

    # Load input feature packets
    print(f"[scorer] Reading feature packets from {args.input}...")
    packets = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                packets.append(json.loads(line))
    
    print(f"[scorer] Loaded {len(packets)} feature packets")

    # Load checkpoint
    checkpoint = load_checkpoint(args.output)
    
    # Filter to unscored packets
    unscored = [p for p in packets if p["id"] not in checkpoint]
    print(f"[scorer] {len(unscored)} packets need scoring ({len(checkpoint)} already scored)")

    if len(unscored) == 0:
        print("[scorer] All packets already scored!")
        return

    # Process in chunks
    all_scored = list(checkpoint.values())
    
    for i in range(0, len(unscored), args.chunk_size):
        chunk = unscored[i:i + args.chunk_size]
        chunk_num = (i // args.chunk_size) + 1
        total_chunks = (len(unscored) + args.chunk_size - 1) // args.chunk_size
        
        print(f"\n[scorer] Processing chunk {chunk_num}/{total_chunks} ({len(chunk)} packets)...")
        
        # Score this chunk
        scores = call_grok_api(chunk, args.api_key or "", mock=args.mock)
        
        # Merge with feature packets and add metadata
        for packet, score in zip(chunk, scores):
            scored_record = {
                **packet,
                "photo_insert_score": score["likelihood"],
                "photo_insert_bucket": score_to_bucket(score["likelihood"]),
                "photo_insert_reasoning": score["reasoning"],
                "scoring_metadata": {
                    "provider": PROVIDER,
                    "model": MODEL_NAME,
                    "prompt_version": PROMPT_VERSION,
                    "run_id": args.run_id or f"run-{int(time.time())}",
                    "timestamp": time.time(),
                }
            }
            all_scored.append(scored_record)
        
        # Checkpoint after each chunk
        save_checkpoint(all_scored, args.output)
        print(f"[scorer] Checkpoint saved ({len(all_scored)} total records)")

    print(f"\n[scorer] Scoring complete! Wrote {len(all_scored)} scored records to {args.output}")
    
    # Print statistics
    buckets = {}
    for record in all_scored:
        bucket = record.get("photo_insert_bucket", "Unknown")
        buckets[bucket] = buckets.get(bucket, 0) + 1
    
    print("\nScore Distribution:")
    for bucket in ["Strongly Likely", "Likely", "Plausible", "Unlikely"]:
        count = buckets.get(bucket, 0)
        pct = count / len(all_scored) * 100 if all_scored else 0
        print(f"  {bucket:20s}: {count:5d} ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
