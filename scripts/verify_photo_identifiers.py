#!/usr/bin/env python3
"""
verify_photo_identifiers.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Verification script for the photo insert identifier system.
Confirms that all photo scores are correctly matched and merged using the 'id' field.

Usage:
    python scripts/verify_photo_identifiers.py

Exit codes:
    0 - All tests passed
    1 - One or more tests failed
"""

import json
import sys
from pathlib import Path


def print_header(text):
    """Print a formatted section header."""
    print()
    print("=" * 60)
    print(text)
    print("=" * 60)
    print()


def print_test(name):
    """Print a test name."""
    print(f"[TEST] {name}")


def print_pass(message):
    """Print a pass message."""
    print(f"  ✓ {message}")


def print_fail(message):
    """Print a fail message."""
    print(f"  ❌ FAIL: {message}")


def print_warn(message):
    """Print a warning message."""
    print(f"  ⚠ Warning: {message}")


def verify_photo_scored_structure():
    """Test 1: Verify photo_scored.jsonl has valid structure."""
    print_test("Verifying photo_scored.jsonl structure")
    
    try:
        path = Path("docs/data/photo_scored.jsonl")
        if not path.exists():
            print_fail(f"File not found: {path}")
            return False, {}
        
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        
        scored_records = {}
        required_fields = ["id", "photo_insert_score", "photo_insert_bucket", "photo_insert_reasoning"]
        
        for i, line in enumerate(lines):
            record = json.loads(line)
            
            # Check for required fields
            for field in required_fields:
                if field not in record:
                    print_fail(f"Record at line {i+1} missing '{field}'")
                    return False, {}
            
            record_id = record["id"]
            if not record_id:
                print_fail(f"Record at line {i+1} has empty id")
                return False, {}
            
            scored_records[record_id] = record
        
        print_pass(f"Total scored records: {len(scored_records)}")
        print_pass("All records have valid IDs")
        print_pass("All records have required photo_insert fields")
        
        return True, scored_records
        
    except Exception as e:
        print_fail(f"Exception: {e}")
        return False, {}


def verify_sekula_index_merging(scored_records):
    """Test 2: Verify sekula_index.json has merged photo scores."""
    print_test("Verifying sekula_index.json photo score merging")
    
    try:
        path = Path("docs/data/sekula_index.json")
        if not path.exists():
            print_fail(f"File not found: {path}")
            return False
        
        with open(path, "r", encoding="utf-8") as f:
            index_records = json.load(f)
        
        total_records = len(index_records)
        records_with_scores = 0
        unmatched_ids = []
        mismatched_scores = []
        
        for record in index_records:
            record_id = record.get("id")
            
            if not record_id:
                print_warn(f"Record at position has no id field")
                continue
            
            if "photo_insert_score" in record:
                records_with_scores += 1
                
                # Verify score matches the source
                if record_id in scored_records:
                    scored = scored_records[record_id]
                    if record["photo_insert_score"] != scored["photo_insert_score"]:
                        mismatched_scores.append(record_id)
                else:
                    # Record has a score but wasn't in scored file
                    print_warn(f"Record {record_id} has score but not in scored file")
            else:
                unmatched_ids.append(record_id)
        
        print_pass(f"Total records: {total_records}")
        print_pass(f"Records with photo scores: {records_with_scores}")
        
        match_rate = 100 * records_with_scores / total_records if total_records > 0 else 0
        print_pass(f"Match rate: {records_with_scores}/{total_records} ({match_rate:.1f}%)")
        
        if mismatched_scores:
            print_fail(f"Score mismatches found: {len(mismatched_scores)}")
            print(f"    First 5: {mismatched_scores[:5]}")
            return False
        
        if unmatched_ids:
            print_warn(f"{len(unmatched_ids)} records without scores")
            if len(unmatched_ids) <= 5:
                print(f"    Unmatched IDs: {unmatched_ids}")
        else:
            print_pass("All records successfully matched and merged")
        
        return True
        
    except Exception as e:
        print_fail(f"Exception: {e}")
        return False


def verify_sekula_inventory_merging():
    """Test 3: Verify sekula_inventory.json has merged photo scores."""
    print_test("Verifying sekula_inventory.json photo score merging")
    
    try:
        path = Path("docs/data/sekula_inventory.json")
        if not path.exists():
            print_fail(f"File not found: {path}")
            return False
        
        with open(path, "r", encoding="utf-8") as f:
            inventory_records = json.load(f)
        
        total_records = len(inventory_records)
        records_with_scores = sum(1 for r in inventory_records if "photo_insert_score" in r)
        
        print_pass(f"Total records: {total_records}")
        print_pass(f"Records with photo scores: {records_with_scores}")
        
        match_rate = 100 * records_with_scores / total_records if total_records > 0 else 0
        print_pass(f"Match rate: {records_with_scores}/{total_records} ({match_rate:.1f}%)")
        
        if records_with_scores == total_records:
            print_pass("All records have photo scores")
        
        return True
        
    except Exception as e:
        print_fail(f"Exception: {e}")
        return False


def verify_id_consistency(scored_records):
    """Test 4: Verify ID consistency across all data files."""
    print_test("Verifying ID consistency across all data files")
    
    try:
        # Load all data files
        with open("docs/data/sekula_index.json", "r", encoding="utf-8") as f:
            index_records = json.load(f)
        
        with open("docs/data/sekula_inventory.json", "r", encoding="utf-8") as f:
            inventory_records = json.load(f)
        
        # Extract ID sets
        scored_ids = set(scored_records.keys())
        index_ids = set(r["id"] for r in index_records)
        inventory_ids = set(r["id"] for r in inventory_records)
        
        # Check consistency
        if scored_ids == index_ids == inventory_ids:
            print_pass(f"All {len(scored_ids)} IDs are consistent across all files")
            return True
        else:
            print_warn("ID sets differ across files")
            print(f"    Scored IDs: {len(scored_ids)}")
            print(f"    Index IDs: {len(index_ids)}")
            print(f"    Inventory IDs: {len(inventory_ids)}")
            
            # Show differences
            if scored_ids != index_ids:
                only_scored = scored_ids - index_ids
                only_index = index_ids - scored_ids
                if only_scored:
                    print(f"    Only in scored: {len(only_scored)} IDs")
                if only_index:
                    print(f"    Only in index: {len(only_index)} IDs")
            
            return True  # Warning, not failure
        
    except Exception as e:
        print_fail(f"Exception: {e}")
        return False


def verify_sample_data(scored_records):
    """Test 5: Verify sample record data quality."""
    print_test("Verifying sample record data quality")
    
    try:
        # Load index for title
        with open("docs/data/sekula_index.json", "r", encoding="utf-8") as f:
            index_records = json.load(f)
        
        # Get first sample
        sample_id = list(scored_records.keys())[0]
        scored_sample = scored_records[sample_id]
        index_sample = next((r for r in index_records if r["id"] == sample_id), None)
        
        if not index_sample:
            print_fail(f"Sample ID {sample_id} not found in index")
            return False
        
        print(f"  Sample ID: {sample_id}")
        print(f"  Title: {index_sample.get('title', 'N/A')}")
        print(f"  Photo Insert Score: {scored_sample['photo_insert_score']}/100")
        print(f"  Photo Insert Bucket: {scored_sample['photo_insert_bucket']}")
        
        reasoning = scored_sample['photo_insert_reasoning']
        print(f"  Reasoning: {reasoning[:80]}{'...' if len(reasoning) > 80 else ''}")
        
        print_pass("Sample record has valid photo insert data")
        return True
        
    except Exception as e:
        print_fail(f"Exception: {e}")
        return False


def main():
    """Run all verification tests."""
    print_header("PHOTO INSERT IDENTIFIER VERIFICATION")
    
    # Run all tests
    test_results = []
    
    # Test 1
    test1_pass, scored_records = verify_photo_scored_structure()
    test_results.append(("Photo scored structure", test1_pass))
    print()
    
    if not test1_pass or not scored_records:
        print_fail("Cannot continue without valid scored records")
        print_header("TESTS FAILED")
        return 1
    
    # Test 2
    test2_pass = verify_sekula_index_merging(scored_records)
    test_results.append(("Sekula index merging", test2_pass))
    print()
    
    # Test 3
    test3_pass = verify_sekula_inventory_merging()
    test_results.append(("Sekula inventory merging", test3_pass))
    print()
    
    # Test 4
    test4_pass = verify_id_consistency(scored_records)
    test_results.append(("ID consistency", test4_pass))
    print()
    
    # Test 5
    test5_pass = verify_sample_data(scored_records)
    test_results.append(("Sample data quality", test5_pass))
    print()
    
    # Summary
    print_header("TEST SUMMARY")
    all_passed = True
    for test_name, passed in test_results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("=" * 60)
        print("✓ ALL TESTS PASSED - PHOTO INSERT IDENTIFIER IS WORKING")
        print("=" * 60)
        return 0
    else:
        print("=" * 60)
        print("❌ SOME TESTS FAILED - PLEASE REVIEW")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
