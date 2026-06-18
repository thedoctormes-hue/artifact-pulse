"""Tests for session_insights_miner_v2 (M5).

This file adds the missing coverage required by the task:

* MD5 deduplication (`_md5_hash`) – case‑insensitive and whitespace‑insensitive.
* Correct metadata tracking (``session_id`` and ``agent_pair``) when an insight is added.
* Semantic deduplication via the Context API – we mock the embedding calls so that
  a candidate that is too similar to an existing insight is filtered out.

The real ``session_insights_miner_v2`` module writes directly to the SQLite
``artifact_insights`` database via :func:`artifact_insights.add_insight`.  For unit
testing we monkey‑patch this function to capture the arguments passed to it instead
of performing any DB writes.  The tests therefore run entirely in‑memory and are
fast.

All tests are written with the ``pytest`` framework and rely only on the standard
library and the project's own modules.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

# Add the project root to ``sys.path`` so imports work from the test runner.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(PROJECT_ROOT))

import session_insights_miner_v2 as miner


# ---------------------------------------------------------------------------
# MD5 deduplication tests (content_hash equivalent)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,reference",
    [
        ("Hello World", "Hello World"),  # identical
        ("hello world", "Hello World"),  # case‑insensitive
        ("   Hello World   ", "Hello World"),  # leading/trailing whitespace
        ("HELLO WORLD", "hello world"),  # all uppercase vs all lowercase
    ],
)
def test_md5_hash_case_and_whitespace(text, reference):
    """Ensure the MD5 hash is case‑insensitive and strips surrounding whitespace.

    The implementation calls ``text.strip().lower()`` before hashing, matching
    the original v1 behaviour.  Note: internal whitespace is preserved — only
    leading/trailing whitespace is removed.
    """
    assert miner._md5_hash(text) == miner._md5_hash(reference)


# ---------------------------------------------------------------------------
# Metadata tracking tests (session_id / agent_pair)
# ---------------------------------------------------------------------------

def _make_dummy_trajectory(tmp_path: Path) -> Path:
    """Create a minimal ``.trajectory.jsonl`` file.

    The miner extracts assistant messages from this file.  We provide a single
    assistant message that will pass the score thresholds.
    """
    traj = tmp_path / "test.trajectory.jsonl"
    # Content must be >= MIN_CONTENT_LENGTH (120 chars) to pass the filter.
    long_content = (
        "Something went wrong with the database connection. "
        "The error indicates a timeout occurred while trying to reach the server. "
        "This is a critical issue that needs immediate attention."
    )
    record = {
        "type": "model.completed",
        "data": {
            "messagesSnapshot": [
                {
                    "role": "assistant",
                    "content": long_content,
                }
            ]
        },
    }
    traj.write_text(json.dumps(record) + "\n")
    return traj


def test_process_session_tracks_metadata(tmp_path, monkeypatch):
    """Verify that ``process_session`` adds the correct ``session_id`` and ``agent_pair``.

    The function calls :func:`artifact_insights.add_insight`.  We replace that
    function with a stub that records the supplied arguments.
    """
    # Prepare a dummy trajectory file in a fake OpenClaw sessions tree.
    openclaw_root = tmp_path / "openclaw"
    session_dir = openclaw_root / "myagent"
    session_dir.mkdir(parents=True)
    traj_path = _make_dummy_trajectory(session_dir)

    # Monkey‑patch constants used by the miner.
    monkeypatch.setattr(miner, "OPENCLAW_SESSIONS_BASE", tmp_path / "openclaw")
    # ``load_queue`` is called at the start of ``main`` but not by ``process_session``.
    # Provide a dummy implementation that returns an empty queue.
    monkeypatch.setattr(miner, "load_queue", lambda: {"insights": []})

    captured = {}

    def fake_add_insight(**kwargs):
        # Store kwargs for later inspection and return a truthy value.
        captured.update(kwargs)
        return True

    # Patch at the name level in the miner module (direct import, not via artifact_insights).
    monkeypatch.setattr(miner, "add_insight", fake_add_insight)

    # Existing hashes / embeddings are empty – the insight should be added.
    added = miner.process_session(traj_path, set(), [])
    assert added == 1

    # The stub should have been called with the expected metadata.
    assert captured["session_id"] == "test"  # stem of the file without extension
    # ``agent_pair`` is ``{agent_name}-session`` where ``agent_name`` is the parent dir name.
    assert captured["agent_pair"] == "myagent-session"
    # The source should be the agent name (parent directory).
    assert captured["source"] == "myagent"


# ---------------------------------------------------------------------------
# Semantic deduplication tests (mocked Ollama embeddings)
# ---------------------------------------------------------------------------

def test_semantic_dedup_filters_similar_candidates(monkeypatch):
    """Mock the embedding API to ensure ``semantic_dedup_batch`` removes duplicates.

    We provide one existing insight with a known embedding and two candidate
    insights – one similar (cosine ≥ threshold) and one dissimilar.  After the
    deduplication step only the dissimilar candidate should remain.
    """
    # Existing insight embedding – a simple unit vector.
    existing_embeddings = [("existing", [1.0, 0.0, 0.0])]

    # Candidate contents – the text itself is irrelevant because we mock the
    # embedding generation.
    candidates = [
        ("similar candidate", "src", "finding", "tag"),
        ("different candidate", "src", "finding", "tag"),
    ]

    # Mock ``get_embedding`` to return vectors that make the first candidate a
    # duplicate (cosine 1.0) and the second orthogonal (cosine 0.0).
    def fake_get_embedding(text):  # pragma: no cover – exercised via mock
        if "similar" in text:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]

    monkeypatch.setattr(miner, "get_embedding", fake_get_embedding)

    filtered = miner.semantic_dedup_batch(candidates, existing_embeddings)

    # Only the second (different) candidate should survive.
    assert len(filtered) == 1
    assert filtered[0][0] == "different candidate"

