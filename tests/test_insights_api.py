"""Tests for insights_api.py (FastAPI REST API).

Tests use TestClient from fastapi.testclient and monkey-patch
the database to use a temporary SQLite file.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary insights.db and patch DB_PATH."""
    db_file = tmp_path / "insights.db"
    with patch("artifact_insights.DB_PATH", db_file):
        # Re-initialize the database in the temp location
        from artifact_insights import _db_init
        _db_init()
        yield db_file


@pytest.fixture
def client(tmp_db):
    """Create a TestClient with a fresh temp database."""
    # Patch _semantic_is_duplicate to skip Ollama calls
    with patch("artifact_insights._semantic_is_duplicate", return_value=False):
        from insights_api import app
        from fastapi.testclient import TestClient
        yield TestClient(app)


# ── Health ────────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "2.0.0"


# ── Create ────────────────────────────────────────────────────────────────────


class TestCreate:
    def test_create_insight(self, client):
        resp = client.post("/insights", json={
            "content": "Test insight from API",
            "source": "antcat",
            "type": "finding",
            "confidence": "high",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Test insight from API"
        assert data["source"] == "antcat"
        assert data["type"] == "finding"
        assert data["status"] == "new"
        assert data["id"].startswith("INS-")

    def test_create_with_tags(self, client):
        resp = client.post("/insights", json={
            "content": "Tagged insight",
            "source": "owl",
            "type": "pattern",
            "tags": "security,auth",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "security" in data["tags"]
        assert "auth" in data["tags"]

    def test_create_with_session_and_pair(self, client):
        resp = client.post("/insights", json={
            "content": "Session insight",
            "source": "dominika",
            "type": "insight",
            "session_id": "sess-abc",
            "agent_pair": "dominika-owl",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["session_id"] == "sess-abc"
        assert data["agent_pair"] == "dominika-owl"

    def test_create_invalid_type(self, client):
        resp = client.post("/insights", json={
            "content": "Bad type",
            "source": "antcat",
            "type": "nonexistent",
        })
        assert resp.status_code == 422  # Pydantic validation

    def test_create_empty_content(self, client):
        resp = client.post("/insights", json={
            "content": "",
            "source": "antcat",
            "type": "finding",
        })
        assert resp.status_code == 422  # min_length=1


# ── List ──────────────────────────────────────────────────────────────────────


class TestList:
    def test_list_empty(self, client):
        resp = client.get("/insights")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["insights"] == []

    def test_list_with_insights(self, client):
        # Create two insights
        for i in range(2):
            client.post("/insights", json={
                "content": f"Insight {i}",
                "source": "antcat",
                "type": "finding",
            })
        resp = client.get("/insights")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_list_filter_by_status(self, client):
        client.post("/insights", json={
            "content": "New insight",
            "source": "antcat",
            "type": "finding",
        })
        resp = client.get("/insights?status=new")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_list_filter_by_source(self, client):
        client.post("/insights", json={
            "content": "From owl",
            "source": "owl",
            "type": "finding",
        })
        resp = client.get("/insights?source=owl")
        assert resp.status_code == 200
        data = resp.json()
        for item in data["insights"]:
            assert item["source"] == "owl"

    def test_list_limit(self, client):
        for i in range(5):
            client.post("/insights", json={
                "content": f"Insight {i}",
                "source": "antcat",
                "type": "finding",
            })
        resp = client.get("/insights?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["insights"]) <= 3


# ── Get by ID ─────────────────────────────────────────────────────────────────


class TestGetById:
    def test_get_existing(self, client):
        created = client.post("/insights", json={
            "content": "Find me",
            "source": "antcat",
            "type": "finding",
        })
        insight_id = created.json()["id"]
        resp = client.get(f"/insights/{insight_id}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Find me"

    def test_get_not_found(self, client):
        resp = client.get("/insights/INS-NONEXISTENT-00000000")
        assert resp.status_code == 404


# ── Verify ────────────────────────────────────────────────────────────────────


class TestVerify:
    def test_verify_insight(self, client):
        created = client.post("/insights", json={
            "content": "Verify me",
            "source": "antcat",
            "type": "finding",
        })
        insight_id = created.json()["id"]
        resp = client.post(f"/insights/{insight_id}/verify")
        assert resp.status_code == 200

    def test_verify_not_found(self, client):
        resp = client.post("/insights/INS-FAKE/verify")
        assert resp.status_code == 404

    def test_verify_twice_promotes_to_verified(self, client):
        created = client.post("/insights", json={
            "content": "Double verify",
            "source": "antcat",
            "type": "finding",
        })
        insight_id = created.json()["id"]
        client.post(f"/insights/{insight_id}/verify")
        resp = client.post(f"/insights/{insight_id}/verify")
        assert resp.status_code == 200
        # After 2 confirmations, status should be "verified"
        get_resp = client.get(f"/insights/{insight_id}")
        assert get_resp.json()["status"] == "verified"


# ── Promote ───────────────────────────────────────────────────────────────────


class TestPromote:
    def test_promote_verified(self, client):
        created = client.post("/insights", json={
            "content": "Promote me",
            "source": "owl",
            "type": "finding",
            "confidence": "high",
        })
        insight_id = created.json()["id"]
        # Verify twice to get to "verified"
        client.post(f"/insights/{insight_id}/verify")
        client.post(f"/insights/{insight_id}/verify")
        # Now promote
        resp = client.post(f"/insights/{insight_id}/promote")
        assert resp.status_code == 200
        assert resp.json()["new_status"] == "artifact"

    def test_promote_not_verified(self, client):
        created = client.post("/insights", json={
            "content": "Not verified",
            "source": "antcat",
            "type": "finding",
        })
        insight_id = created.json()["id"]
        # Don't verify — status is still "new"
        resp = client.post(f"/insights/{insight_id}/promote")
        assert resp.status_code == 400

    def test_promote_not_found(self, client):
        resp = client.post("/insights/INS-FAKE/promote")
        assert resp.status_code == 400


# ── Stats ─────────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty(self, client):
        resp = client.get("/insights/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_stats_with_data(self, client):
        client.post("/insights", json={
            "content": "Stat insight",
            "source": "antcat",
            "type": "finding",
        })
        resp = client.get("/insights/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert "by_status" in data
        assert "by_type" in data
        assert "by_source" in data
