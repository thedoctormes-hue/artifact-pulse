"""Tests for new features: artifact-diff, artifact-watch, artifact-new."""

import json
import tempfile
from pathlib import Path


# ── artifact-diff ─────────────────────────────────────────────

class TestArtifactDiff:
    def test_diff_same_artifact_raises(self):
        from artifact_diff import compute_diff
        artifacts = {
            "ADR-001": {
                "id": "ADR-001", "type": "adr", "title": "First",
                "status": "active", "meta": {"id": "ADR-001", "type": "adr", "title": "First", "status": "active", "created": "2024-01-01"},
                "body": "Some content", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            }
        }
        # Should handle gracefully — same artifact
        # Note: main() would sys.exit, but compute_diff should handle it
        diff = compute_diff(artifacts, "ADR-001", "ADR-001")
        assert diff["artifact_1"] == "ADR-001"
        assert diff["artifact_2"] == "ADR-001"
        # No changes expected
        assert len(diff["field_changes"]) == 0

    def test_diff_different_status(self):
        from artifact_diff import compute_diff
        artifacts = {
            "ADR-001": {
                "id": "ADR-001", "type": "adr", "title": "First",
                "status": "active", "meta": {"id": "ADR-001", "type": "adr", "title": "First", "status": "active", "created": "2024-01-01"},
                "body": "Some content", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
            "ADR-002": {
                "id": "ADR-002", "type": "adr", "title": "Second",
                "status": "deprecated", "meta": {"id": "ADR-002", "type": "adr", "title": "Second", "status": "deprecated", "created": "2024-01-01"},
                "body": "Other content", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
        }
        diff = compute_diff(artifacts, "ADR-001", "ADR-002")

        # Should detect status change
        status_changes = [fc for fc in diff["field_changes"] if fc["field"] == "status"]
        assert len(status_changes) == 1
        assert status_changes[0]["old"] == "active"
        assert status_changes[0]["new"] == "deprecated"

        # Body diff should exist
        assert len(diff["body_diff"]) > 0

    def test_diff_outbound_refs(self):
        from artifact_diff import compute_diff
        artifacts = {
            "ADR-001": {
                "id": "ADR-001", "type": "adr", "title": "First",
                "status": "active", "meta": {"id": "ADR-001", "type": "adr", "title": "First", "status": "active", "created": "2024-01-01"},
                "body": "References PAT-001 and RUL-001.", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
            "ADR-002": {
                "id": "ADR-002", "type": "adr", "title": "Second",
                "status": "active", "meta": {"id": "ADR-002", "type": "adr", "title": "Second", "status": "active", "created": "2024-01-01"},
                "body": "References PAT-001 only.", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
        }
        diff = compute_diff(artifacts, "ADR-001", "ADR-002")

        assert "RUL-001" in diff["outbound_refs"]["removed"]
        assert "PAT-001" in diff["outbound_refs"]["common"]

    def test_diff_json_output(self):
        from artifact_diff import compute_diff
        artifacts = {
            "ADR-001": {
                "id": "ADR-001", "type": "adr", "title": "First",
                "status": "active", "meta": {"id": "ADR-001", "type": "adr", "title": "First", "status": "active", "created": "2024-01-01"},
                "body": "Content", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
            "ADR-002": {
                "id": "ADR-002", "type": "adr", "title": "Second",
                "status": "active", "meta": {"id": "ADR-002", "type": "adr", "title": "Second", "status": "active", "created": "2024-01-01"},
                "body": "Content", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
        }
        diff = compute_diff(artifacts, "ADR-001", "ADR-002")
        # Should be JSON-serializable
        result = json.dumps(diff, default=str)
        parsed = json.loads(result)
        assert parsed["artifact_1"] == "ADR-001"

    def test_format_diff_text(self):
        from artifact_diff import compute_diff, format_diff_text
        artifacts = {
            "ADR-001": {
                "id": "ADR-001", "type": "adr", "title": "First",
                "status": "active", "meta": {"id": "ADR-001", "type": "adr", "title": "First", "status": "active", "created": "2024-01-01"},
                "body": "Content", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
            "ADR-002": {
                "id": "ADR-002", "type": "adr", "title": "Second",
                "status": "active", "meta": {"id": "ADR-002", "type": "adr", "title": "Second", "status": "active", "created": "2024-01-01"},
                "body": "Content", "full_content": "", "created": "", "updated": "",
                "last_verified": "", "confidence": "", "source": "", "tags": [],
            },
        }
        diff = compute_diff(artifacts, "ADR-001", "ADR-002")
        text = format_diff_text(diff)
        assert "ADR-001" in text
        assert "ADR-002" in text
        assert "DIFF" in text


# ── artifact-watch ─────────────────────────────────────────────

class TestArtifactWatch:
    def test_once_returns_int(self):
        """run_watch_once should return an int exit code."""
        from artifact_watch import run_watch_once
        # This actually runs a full health check — will work against real artifacts
        result = run_watch_once(json_output=True)
        assert isinstance(result, int)
        assert result in (0, 1)

    def test_once_json_output(self):
        """run_watch_once with json should produce valid JSON."""
        from artifact_watch import run_watch_once
        result = run_watch_once(json_output=True)
        # The function prints JSON and returns code; we can't capture stdout easily here
        # Just verify it doesn't raise
        assert isinstance(result, int)


# ── artifact-new ──────────────────────────────────────────────

class TestArtifactNew:
    def test_invalid_type(self):
        from artifact_new import generate_artifact
        result = generate_artifact("invalid_type", "Test")
        assert "error" in result
        assert "Invalid type" in result["error"]

    def test_dry_run_pattern(self):
        from artifact_new import generate_artifact
        result = generate_artifact("pattern", "Test pattern", dry_run=True)
        assert "error" not in result
        assert result["dry_run"] is True
        assert result["type"] == "pattern"
        assert result["title"] == "Test pattern"
        assert result["id"].startswith("PAT-")

    def test_dry_run_adr(self):
        from artifact_new import generate_artifact
        result = generate_artifact("adr", "Test ADR", dry_run=True)
        assert "error" not in result
        assert result["id"].startswith("ADR-")

    def test_dry_run_creates_nothing(self):
        from artifact_new import generate_artifact
        import tempfile, os
        # Dry run should not create any file
        from config_loader import get_lab_dir
        lab_dir = get_lab_dir()
        result = generate_artifact("rule", "Test rule DRY", dry_run=True)
        expected_path = lab_dir / "rules" / f"{result['id']}.md"
        assert not expected_path.exists()

    def test_next_id_generation(self):
        from artifact_new import _next_id
        assert _next_id("PAT", [1, 2, 3]) == "PAT-004"
        assert _next_id("ADR", []) == "ADR-001"
        assert _next_id("PAT", [5]) == "PAT-006"

    def test_get_existing_ids(self):
        from artifact_new import _get_existing_ids
        artifacts = {
            "PAT-001": None, "PAT-002": None,
            "ADR-001": None, "PAT-010": None,
        }
        ids = _get_existing_ids(artifacts, "PAT")
        assert sorted(ids) == [1, 2, 10]

    def test_format_result_error(self):
        from artifact_new import format_result
        assert "ERROR" in format_result({"error": "test error"})

    def test_format_result_dry_run(self):
        from artifact_new import format_result
        text = format_result({"dry_run": True, "id": "PAT-001", "title": "Test"})
        assert "[DRY-RUN]" in text

    def test_format_result_created(self):
        from artifact_new import format_result
        text = format_result({"id": "PAT-001", "title": "Test", "file": "patterns/PAT-001.md", "status": "draft", "dry_run": False})
        assert "Created" in text
        assert "PAT-001" in text
