#!/usr/bin/env python3

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
from unittest import mock
import tempfile
import unittest

import upload_jefferson_private_review_release as uploader


FAKE_WRANGLER = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

arguments = sys.argv[1:]
log_path = Path(os.environ["FAKE_WRANGLER_LOG"])
log_path.parent.mkdir(parents=True, exist_ok=True)
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(arguments, separators=(",", ":")) + "\n")

if len(arguments) < 6 or arguments[:2] != ["r2", "object"]:
    raise SystemExit(91)
operation = arguments[2]
object_path = arguments[3]
if "--remote" not in arguments or "--file" not in arguments:
    raise SystemExit(92)
file_path = Path(arguments[arguments.index("--file") + 1])
remote_path = Path(os.environ["FAKE_R2_ROOT"]).joinpath(*object_path.split("/"))
failure = os.environ.get("FAKE_WRANGLER_FAIL", "")
if failure == operation:
    raise SystemExit(23)

if operation == "put":
    if "--force" not in arguments:
        raise SystemExit(95)
    if arguments[arguments.index("--storage-class") + 1] != "Standard":
        raise SystemExit(93)
    remote_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(file_path, remote_path)
elif operation == "get":
    file_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(remote_path, file_path)
    if os.environ.get("FAKE_WRANGLER_TAMPER_GET") == "1":
        with file_path.open("ab") as handle:
            handle.write(b"tampered")
else:
    raise SystemExit(94)
'''


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class PrivateReviewUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="private review uploader tests ")
        self.root = Path(self.temporary.name)
        self.private_root = self.root / "private review"
        self.remote_root = self.root / "fake remote"
        self.log_path = self.root / "wrangler calls.jsonl"
        self.fake_wrangler = self.root / "fake wrangler"
        self.fake_wrangler.write_text(FAKE_WRANGLER, encoding="utf-8")
        self.fake_wrangler.chmod(0o755)
        self.active_path, self.release_root, self.release = self.make_release()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_release(self) -> tuple[Path, Path, dict[str, object]]:
        public_manifest = b'{"collection_id":"jefferson"}\n'
        private_media_manifest = b'{"audience":"authenticated_review","items":[]}\n'
        contents = {
            ".nojekyll": b"\n",
            "data/collections/jefferson/manifest.json": public_manifest,
            "data/collections/jefferson/media-authenticated.json": private_media_manifest,
            "index.html": b"<!doctype html><title>Private review</title>\n",
            "preview/exhibit/index.html": b"<!doctype html><title>Preview</title>\n",
            "preview.png": b"not-really-a-png",
        }
        site_files = [
            {"path": path, "bytes": len(body), "sha256": sha256_bytes(body)}
            for path, body in sorted(
                contents.items(), key=lambda item: uploader.site_path_sort_key(item[0])
            )
        ]
        basis: dict[str, object] = {
            "schema": uploader.RELEASE_SCHEMA,
            "collection_id": "jefferson",
            "generated_at": "2026-08-02T02:00:00Z",
            "access": "cloudflare_access_authenticated_review",
            "public_manifest_sha256": sha256_bytes(public_manifest),
            "private_media_manifest_sha256": sha256_bytes(private_media_manifest),
            "site_files": site_files,
        }
        release_id = sha256_bytes(uploader.canonical_json(basis)).removeprefix("sha256:")
        release: dict[str, object] = {
            **basis,
            "release_id": release_id,
            "site_file_count": len(site_files),
            "site_bytes": sum(len(body) for body in contents.values()),
            "private_photo_count": 4,
        }
        release_root = self.private_root / "releases" / release_id
        site_root = release_root / "site"
        for relative, body in contents.items():
            target = site_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        (release_root / "release.json").write_bytes(uploader.canonical_json(release))
        active = {
            "schema": uploader.ACTIVE_SCHEMA,
            "release_id": release_id,
            "release_path": f"releases/{release_id}",
        }
        active_path = self.private_root / "active.json"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_bytes(uploader.canonical_json(active))
        return active_path, release_root, release

    def invoke(self, *extra: str, environment: dict[str, str] | None = None):
        arguments = [
            "--bucket",
            "shelfsignals-private-review",
            "--active-manifest",
            str(self.active_path),
            "--wrangler",
            str(self.fake_wrangler),
            *extra,
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        fake_environment = {
            "FAKE_R2_ROOT": str(self.remote_root),
            "FAKE_WRANGLER_LOG": str(self.log_path),
        }
        if environment:
            fake_environment.update(environment)
        with mock.patch.dict(os.environ, fake_environment, clear=False):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = uploader.main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def calls(self) -> list[list[str]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def assert_preflight_failure(self, pattern: str) -> None:
        result, _, stderr = self.invoke()
        self.assertEqual(result, 2)
        self.assertRegex(stderr, pattern)
        self.assertEqual(self.calls(), [], "preflight failure must happen before Wrangler runs")

    def test_dry_run_validates_without_invoking_wrangler(self) -> None:
        result, stdout, stderr = self.invoke("--dry-run")
        self.assertEqual(result, 0, stderr)
        summary = json.loads(stdout)
        self.assertTrue(summary["dry_run"])
        self.assertFalse(summary["verified"])
        self.assertEqual(summary["object_count"], len(self.release["site_files"]) + 1)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.remote_root.exists())

    def test_uploads_only_declared_objects_then_downloads_and_verifies_all(self) -> None:
        result, stdout, stderr = self.invoke()
        self.assertEqual(result, 0, stderr)
        summary = json.loads(stdout)
        self.assertTrue(summary["verified"])
        calls = self.calls()
        object_count = len(self.release["site_files"]) + 1
        self.assertEqual(len(calls), object_count * 2)
        puts = calls[:object_count]
        gets = calls[object_count:]
        self.assertTrue(all(call[:3] == ["r2", "object", "put"] for call in puts))
        self.assertTrue(all(call[:3] == ["r2", "object", "get"] for call in gets))
        self.assertTrue(all("--remote" in call and "--file" in call for call in calls))
        self.assertTrue(all("--force" in call for call in puts))
        self.assertTrue(all("--force" not in call for call in gets))
        self.assertTrue(
            all(
                call[call.index("--storage-class") + 1] == "Standard"
                for call in puts
            )
        )
        flattened = {argument for call in calls for argument in call}
        self.assertNotIn("list", flattened)
        self.assertNotIn("delete", flattened)

        release_id = str(self.release["release_id"])
        expected_keys = [
            f"releases/{release_id}/site/{entry['path']}"
            for entry in self.release["site_files"]
        ] + [f"releases/{release_id}/release.json"]
        self.assertEqual([call[3].split("/", 1)[1] for call in puts], expected_keys)
        self.assertEqual([call[3].split("/", 1)[1] for call in gets], expected_keys)
        remote_files = sorted(
            path.relative_to(self.remote_root / "shelfsignals-private-review").as_posix()
            for path in (self.remote_root / "shelfsignals-private-review").rglob("*")
            if path.is_file()
        )
        self.assertEqual(remote_files, sorted(expected_keys))
        self.assertIn(f"Uploaded {object_count}/{object_count} objects", stderr)
        self.assertIn(
            f"Verified {object_count}/{object_count} remote objects", stderr
        )

    def test_tampered_site_file_fails_before_network(self) -> None:
        (self.release_root / "site/index.html").write_bytes(b"tampered")
        self.assert_preflight_failure("Byte-count mismatch|SHA-256 mismatch")

    def test_unexpected_site_file_fails_before_network(self) -> None:
        (self.release_root / "site/unexpected.txt").write_text("extra", encoding="utf-8")
        self.assert_preflight_failure("inventory mismatch")

    def test_unsafe_manifest_path_fails_before_network(self) -> None:
        release_path = self.release_root / "release.json"
        release = json.loads(release_path.read_text(encoding="utf-8"))
        release["site_files"][0]["path"] = "../escape"
        release_path.write_bytes(uploader.canonical_json(release))
        self.assert_preflight_failure("unsafe")

    def test_wrong_release_id_fails_before_network(self) -> None:
        release_path = self.release_root / "release.json"
        release = json.loads(release_path.read_text(encoding="utf-8"))
        release["generated_at"] = "2026-08-02T02:00:01Z"
        release_path.write_bytes(uploader.canonical_json(release))
        self.assert_preflight_failure("Release ID does not match")

    def test_symlink_in_site_fails_before_network(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (self.release_root / "site/linked.txt").symlink_to(outside)
        self.assert_preflight_failure("unsafe directory entry|non-symlink|inventory mismatch")

    def test_malicious_bucket_name_fails_before_network(self) -> None:
        arguments = [
            "--bucket",
            "safe; r2 object delete victim/key",
            "--active-manifest",
            str(self.active_path),
            "--wrangler",
            str(self.fake_wrangler),
        ]
        output = io.StringIO()
        with redirect_stderr(output):
            result = uploader.main(arguments)
        self.assertEqual(result, 2)
        self.assertRegex(output.getvalue(), "bucket name")
        self.assertEqual(self.calls(), [])

    def test_manifest_hash_mismatch_fails_before_network(self) -> None:
        release_path = self.release_root / "release.json"
        release = json.loads(release_path.read_text(encoding="utf-8"))
        release["public_manifest_sha256"] = f"sha256:{'1' * 64}"
        basis = {key: release[key] for key in uploader.RELEASE_BASIS_KEYS}
        release_id = sha256_bytes(uploader.canonical_json(basis)).removeprefix("sha256:")
        release["release_id"] = release_id
        release_path.write_bytes(uploader.canonical_json(release))
        active = {
            "schema": uploader.ACTIVE_SCHEMA,
            "release_id": release_id,
            "release_path": f"releases/{release_id}",
        }
        new_root = self.private_root / "releases" / release_id
        self.release_root.rename(new_root)
        self.release_root = new_root
        self.active_path.write_bytes(uploader.canonical_json(active))
        self.assert_preflight_failure("does not match its declared site file")

    def test_credentials_are_not_emitted_or_passed_to_wrangler(self) -> None:
        secret = "test-token-that-must-not-leak"
        result, stdout, stderr = self.invoke(
            environment={"CLOUDFLARE_API_TOKEN": secret}
        )
        self.assertEqual(result, 0, stderr)
        self.assertNotIn(secret, stdout)
        self.assertNotIn(secret, stderr)
        self.assertNotIn(secret, json.dumps(self.calls()))

    def test_wrangler_error_stops_immediately(self) -> None:
        result, _, stderr = self.invoke(environment={"FAKE_WRANGLER_FAIL": "put"})
        self.assertEqual(result, 2)
        self.assertRegex(stderr, "Wrangler put failed")
        self.assertEqual(len(self.calls()), 1)

    def test_remote_hash_mismatch_fails_after_upload(self) -> None:
        result, _, stderr = self.invoke(
            environment={"FAKE_WRANGLER_TAMPER_GET": "1"}
        )
        self.assertEqual(result, 2)
        self.assertRegex(stderr, "Remote byte-count mismatch|Remote SHA-256 mismatch")
        object_count = len(self.release["site_files"]) + 1
        calls = self.calls()
        self.assertEqual(len(calls), object_count + 1)
        self.assertTrue(all(call[2] == "put" for call in calls[:object_count]))
        self.assertEqual(calls[-1][2], "get")


if __name__ == "__main__":
    unittest.main()
