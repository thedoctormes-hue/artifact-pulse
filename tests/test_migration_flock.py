#!/usr/bin/env python3
"""
Test suite for the migration from JSON queue to SQLite and basic SQLite operations.
It verifies:
1. `migrate_json_to_sqlite` correctly migrates unique insights and skips duplicates.
2. `artifact_insights.save_insight` and `load_insights` work with the SQLite DB.
"""

import json
import sqlite3
from pathlib import Path


# Import the migration function and SQLite helpers from the project
from scripts.migrate_to_sqlite import migrate_json_to_sqlite
import artifact_insights
from artifact_insights import (
    _db_init,
    DB_PATH,
)


def create_sample_json(tmp_dir: Path):
    """Create a temporary insights_queue.json with sample data, including a duplicate ID."""
    data = {
        "insights": [
            {
                "id": "INS-001",
                "timestamp": "2026-06-18T10:00:00+00:00",
                "content": "First insight",
                "type": "finding",
                "source": "test",
                "status": "new",
            },
            {
                "id": "INS-002",
                "timestamp": "2026-06-18T10:01:00+00:00",
                "content": "Second insight",
                "type": "error",
                "source": "test",
                "status": "new",
            },
            # Duplicate of INS-001 – should be skipped during migration
            {
                "id": "INS-001",
                "timestamp": "2026-06-18T10:02:00+00:00",
                "content": "Duplicate insight",
                "type": "finding",
                "source": "test",
                "status": "new",
            },
        ]
    }
    json_path = tmp_dir / "insights_queue.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")
    return json_path


def test_migration_creates_sqlite_and_skips_duplicates(tmp_path: Path):
    # Prepare temporary JSON file
    json_path = create_sample_json(tmp_path)
    # Use a temporary DB path to avoid clobbering real data
    db_path = tmp_path / "test_insights.db"

    # Run migration
    stats = migrate_json_to_sqlite(str(json_path), str(db_path), verify=False)

    # Verify statistics – 3 total, 2 migrated, 1 skipped (duplicate)
    assert stats["total"] == 3
    assert stats["migrated"] == 2
    assert stats["skipped"] == 1
    assert stats["errors"] == 0

    # Connect to the DB and check rows
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT id, content FROM insights ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 2
    ids = {r[0] for r in rows}
    assert ids == {"INS-001", "INS-002"}
    # Ensure the content for INS-001 is the first one (duplicate was ignored)
    content_map = {r[0]: r[1] for r in rows}
    assert content_map["INS-001"] == "First insight"


def test_save_and_load_insight_roundtrip(tmp_path: Path):
    # Point the global DB_PATH to a temporary file for isolation
    original_db = DB_PATH
    try:
        # Monkey‑patch the DB_PATH constant used inside artifact_insights
        artifact_insights.DB_PATH = tmp_path / "temp_insights.db"
        # Ensure fresh DB
        _db_init()

        insight = {
            "id": "INS-TEST",
            "timestamp": "2026-06-18T12:00:00+00:00",
            "content": "Test insight for save/load",
            "type": "pattern",
            "source": "unit-test",
            "status": "new",
            "confidence": "high",
            "tags": ["unit", "test"],
        }
        # Save the insight
        artifact_insights.save_insight(insight)
        # Load back (no filter)
        loaded = artifact_insights.load_insights(limit=10)
        # Find our insight by ID
        matched = [i for i in loaded if i["id"] == "INS-TEST"]
        assert matched, "Insight not found after save"
        loaded_insight = matched[0]
        # Verify key fields round‑tripped correctly
        assert loaded_insight["content"] == insight["content"]
        assert loaded_insight["type"] == insight["type"]
        assert set(loaded_insight["tags"]) == set(
            insight["tags"]
        )  # tags are stored as list
    finally:
        # Restore original DB_PATH to avoid side effects for other tests
        artifact_insights.DB_PATH = original_db
