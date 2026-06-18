#!/usr/bin/env python3
"""
artifact_insights.py — Модуль приёма и консолидации инсайтов для artifact-pulse.

Status flow: new → verified → artifact

Использование:
  python3 artifact_insights.py add --content "..." --source "agent" --type "finding" [--confidence high] [--context "..."] [--tags "t1,t2"]
  python3 artifact_insights.py list [--status new] [--limit 20]
  python3 artifact_insights.py consolidate [--min-confidence 0.7]
  python3 artifact_insights.py verify --id INS-XXX
  python3 artifact_insights.py promote --id INS-XXX
  python3 artifact_insights.py stats
"""

import argparse
import json
import hashlib
import sys
import math
import sqlite3
import struct
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Ollama bge-m3 (semantic dedup) ──────────────────────────────────────────
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3-cpu"
SEMANTIC_DUP_THRESHOLD = 0.85

DB_PATH = Path(__file__).parent.parent.parent / ".qwen" / "artifacts" / "insights.db"

# Concurrency: WAL mode + BEGIN IMMEDIATE transactions + flock
import fcntl as _fcntl  # noqa: E402

_flock_fd = None
_lock_path = Path(__file__).parent / ".insights.lock"


def _flock_acquire():
    global _flock_fd
    _flock_fd = open(_lock_path, "w")
    _fcntl.flock(_flock_fd, _fcntl.LOCK_EX)


def _flock_release():
    global _flock_fd
    if _flock_fd:
        _fcntl.flock(_flock_fd, _fcntl.LOCK_UN)
        _flock_fd.close()
        _flock_fd = None


FAISS_INDEX_PATH = (
    Path(__file__).parent.parent.parent / ".qwen" / "artifacts" / "insights.faiss"
)

ARTIFACT_DIRS = {
    "adr": "adr/",
    "pattern": "patterns/",
    "rule": "rules/",
    "incident": "incidents/",
    "spec": "specs/",
    "metric": "metrics/",
}
VALID_TYPES = {
    "error",
    "decision",
    "finding",
    "pattern",
    "anti-pattern",
    "insight",
    "security",
}
VALID_CONFIDENCE = {"low": 0.3, "medium": 0.6, "high": 0.9}
VALID_STATUS = {"new", "verified", "artifact", "rejected", "archived"}

# ── SQLite ───────────────────────────────────────────────────────────────────


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _db_init():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS insights (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            tool TEXT DEFAULT 'manual',
            context TEXT DEFAULT '',
            content TEXT NOT NULL,
            importance REAL DEFAULT 0.6,
            status TEXT DEFAULT 'new',
            confirmations INTEGER DEFAULT 0,
            source TEXT NOT NULL,
            type TEXT NOT NULL,
            confidence TEXT DEFAULT 'medium',
            tags TEXT DEFAULT '',
            session_id TEXT DEFAULT '',
            agent_pair TEXT DEFAULT '',
            embedding BLOB,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ins_status ON insights(status);
        CREATE INDEX IF NOT EXISTS idx_ins_type ON insights(type);
        CREATE INDEX IF NOT EXISTS idx_ins_source ON insights(source);
    """)
    conn.commit()
    conn.close()


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    # parse tags back to list
    if d.get("tags"):
        d["tags"] = [t.strip() for t in d["tags"].split(",") if t.strip()]
    else:
        d["tags"] = []
    return d


def load_queue() -> dict:
    """Compatibility wrapper – returns {'insights': list} for the miner v2."""
    return {"insights": load_insights()}


def load_insights(status_filter: str = None, limit: int = 500) -> list:
    _db_init()
    conn = _get_db()
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM insights WHERE status = ? ORDER BY timestamp DESC LIMIT ?",
            (status_filter, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM insights ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    result = [_row_to_dict(r) for r in rows]
    conn.close()
    return result


def save_insight(insight: dict):
    _flock_acquire()
    try:
        _db_init()
        conn = _get_db()
        conn.execute("BEGIN IMMEDIATE")
        tags = insight.get("tags", [])
        if isinstance(tags, list):
            tags = ",".join(tags)
        conn.execute(
            """
            INSERT OR REPLACE INTO insights
            (id, timestamp, tool, context, content, importance, status, confirmations,
             source, type, confidence, tags, session_id, agent_pair, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
            (
                insight["id"],
                insight["timestamp"],
                insight.get("tool", "manual"),
                insight.get("context", ""),
                insight["content"],
                insight.get("importance", 0.6),
                insight.get("status", "new"),
                insight.get("confirmations", 0),
                insight["source"],
                insight["type"],
                insight.get("confidence", "medium"),
                tags,
                insight.get("session_id", ""),
                insight.get("agent_pair", ""),
            ),
        )
        conn.commit()
        conn.close()
    finally:
        _flock_release()


def update_status(insight_id: str, new_status: str) -> bool:
    if new_status not in VALID_STATUS:
        print(
            f"Ошибка: неизвестный статус '{new_status}'. Допустимые: {', '.join(sorted(VALID_STATUS))}"
        )
        return False
    _flock_acquire()
    try:
        _db_init()
        conn = _get_db()
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE insights SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, insight_id),
        )
        conn.commit()
        found = cur.rowcount > 0
        conn.close()
        return found
    finally:
        _flock_release()


# ── Embedding / Dedup ────────────────────────────────────────────────────────


def _cosine_sim(a: list, b: list) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _get_embedding(text: str, max_retries: int = 2) -> list:
    """Get embedding from Ollama with strict 5s timeout.
    
    FAISS is the primary dedup engine — Ollama is only used to get
    the new vector for FAISS lookup. If Ollama hangs, we skip it.
    """
    import time as _time

    data = json.dumps({"model": EMBED_MODEL, "prompt": text[:512]}).encode()
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/embeddings",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
            return result.get("embedding", [])
        except urllib.error.HTTPError as e:
            if e.code == 500 and attempt < max_retries - 1:
                _time.sleep(1)
                continue
            print(f"[embed warn] HTTP {e.code}: {e.reason}", file=sys.stderr)
            return []
        except Exception as e:
            if attempt < max_retries - 1:
                _time.sleep(1)
                continue
            print(f"[embed warn] {e}", file=sys.stderr)
            return []
    return []


def _semantic_is_duplicate(content: str) -> bool:
    """Check for semantic duplicates using FAISS first, then exact text match fallback."""
    # Primary: FAISS (fast, one Ollama call for the new text only)
    try:
        import faiss
        import numpy as np

        if FAISS_INDEX_PATH.exists():
            index = faiss.read_index(str(FAISS_INDEX_PATH))
            vec = _get_embedding(content)
            if vec:
                vec_np = np.array([vec], dtype=np.float32)
                faiss.normalize_L2(vec_np)
                distances, indices = index.search(vec_np, 3)
                if distances[0][0] >= SEMANTIC_DUP_THRESHOLD:
                    return True
                else:
                    # FAISS found results but none above threshold → not a duplicate
                    return False
    except Exception as e:
        print(f"[dedup warn] FAISS failed: {e}", file=sys.stderr)

    # Fallback: exact text match (no Ollama needed)
    _db_init()
    conn = _get_db()
    row = conn.execute(
        "SELECT id FROM insights WHERE lower(content) = lower(?)", (content.strip(),)
    ).fetchone()
    conn.close()
    if row:
        return True

    # Last resort: if FAISS unavailable, use Ollama for pairwise comparison
    qvec = _get_embedding(content)
    if not qvec:
        return False  # Can't determine, assume not duplicate

    recent = load_insights(limit=50)
    for existing in recent:
        evec = existing.get("embedding", [])
        if isinstance(evec, bytes):
            evec = list(struct.unpack(f"{len(evec)//4}f", evec))
        if not evec:
            evec = _get_embedding(existing["content"])
        if evec and _cosine_sim(qvec, evec) >= SEMANTIC_DUP_THRESHOLD:
            return True
    return False


# ── CRUD ─────────────────────────────────────────────────────────────────────


def generate_id(content: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    h = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"INS-{ts}-{h}"


def add_insight(
    content: str,
    source: str,
    insight_type: str,
    confidence: str = "medium",
    context: str = "",
    tags: str = "",
    tool: str = "",
    session_id: str = "",
    agent_pair: str = "",
) -> dict:
    if not content or not content.strip():
        raise ValueError("content cannot be empty")
    if insight_type not in VALID_TYPES:
        raise ValueError(
            f"Unknown type '{insight_type}'. Valid: {sorted(VALID_TYPES)}"
        )
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(
            f"Unknown confidence '{confidence}'. Valid: {list(VALID_CONFIDENCE.keys())}"
        )

    if _semantic_is_duplicate(content):
        print("Дубликат (semantic): инсайт уже существует, пропускаем")
        return {}

    insight = {
        "id": generate_id(content),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool or "manual",
        "context": context,
        "content": content,
        "importance": VALID_CONFIDENCE[confidence],
        "status": "new",
        "confirmations": 0,
        "source": source,
        "type": insight_type,
        "confidence": confidence,
        "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
        "session_id": session_id,
        "agent_pair": agent_pair,
    }
    save_insight(insight)
    print(
        f"✅ Инсайт записан: {insight['id']} (type={insight_type}, confidence={confidence})"
    )
    return insight


def list_insights(status: str = None, limit: int = 20, source: str = None):
    insights = load_insights(status_filter=status, limit=limit)
    if source:
        insights = [i for i in insights if i.get("source") == source]

    total = len(insights)
    print(
        f"Всего инсайтов: {total}"
        + (f" (показано последние {limit})" if total > limit else "")
    )
    print()
    for i in insights[:limit]:
        tags = ", ".join(i.get("tags", []))
        print(f"  [{i['status']}] {i['id']}")
        print(
            f"    type={i.get('type','?')}  confidence={i.get('confidence','?')}  source={i.get('source','?')}"
        )
        print(f"    content: {i['content'][:120]}")
        if tags:
            print(f"    tags: {tags}")
        print()


def consolidate(min_confidence: float = 0.5):
    """Status flow: new → verified (confirmations>=2), verified → artifact (importance>=threshold)."""
    _flock_acquire()
    try:
        _db_init()
        conn = _get_db()
        conn.execute("BEGIN IMMEDIATE")

        # new → verified: need >= 2 confirmations
        cur1 = conn.execute("""
            UPDATE insights SET status = 'verified', updated_at = datetime('now')
            WHERE status = 'new' AND confirmations >= 2
        """)
        new_to_verified = cur1.rowcount

        # verified → artifact: need importance >= threshold from trusted sources
        cur2 = conn.execute(
            """
            UPDATE insights SET status = 'artifact', updated_at = datetime('now')
            WHERE status = 'verified'
            AND importance >= ?
            AND source IN ('owl', 'dominika', 'antcat', 'sessions', 'manual', 'bestia', 'kotolizator', 'mangust', 'voron', 'shtreykbreher')
        """,
            (min_confidence,),
        )
        verified_to_artifact = cur2.rowcount

        conn.commit()

        print(f"new → verified: {new_to_verified}")
        print(f"verified → artifact: {verified_to_artifact}")

        stats = conn.execute(
            "SELECT status, COUNT(*) as c FROM insights GROUP BY status ORDER BY c DESC"
        ).fetchall()
        print("\nТекущее распределение:")
        for s, c in stats:
            print(f"  {s}: {c}")
        conn.close()
    finally:
        _flock_release()


def show_stats():
    _db_init()
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
    by_status = conn.execute(
        "SELECT status, COUNT(*) as c FROM insights GROUP BY status ORDER BY c DESC"
    ).fetchall()
    by_type = conn.execute(
        "SELECT type, COUNT(*) as c FROM insights GROUP BY type ORDER BY c DESC"
    ).fetchall()
    by_source = conn.execute(
        "SELECT source, COUNT(*) as c FROM insights GROUP BY source ORDER BY c DESC"
    ).fetchall()

    print(f"Всего инсайтов: {total}\n")
    print("По статусам:")
    for s, c in by_status:
        print(f"  {s}: {c}")
    print("По типам:")
    for t, c in by_type:
        print(f"  {t}: {c}")
    print("По источникам:")
    for src, c in by_source:
        print(f"  {src}: {c}")
    conn.close()


def verify_insight(insight_id: str):
    """Increment confirmations. Auto-promote new→verified if confirmations>=2."""
    _flock_acquire()
    try:
        _db_init()
        conn = _get_db()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, confirmations, status FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Insight {insight_id} not found")

        new_conf = row["confirmations"] + 1
        new_status = (
            "verified" if new_conf >= 2 and row["status"] == "new" else row["status"]
        )
        conn.execute(
            "UPDATE insights SET confirmations = ?, status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_conf, new_status, insight_id),
        )
        conn.commit()
        conn.close()
        print(
            f"✅ Инсайт {insight_id} подтверждён (confirmations={new_conf}, status={new_status})"
        )
        return True
    finally:
        _flock_release()


def promote_insight(insight_id: str):
    """Promote verified → artifact."""
    _flock_acquire()
    try:
        _db_init()
        conn = _get_db()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, status, importance FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Insight {insight_id} not found")
        if row["status"] != "verified":
            conn.close()
            raise ValueError(f"Insight {insight_id} status is '{row['status']}', expected 'verified'")
        conn.execute(
            "UPDATE insights SET status = 'artifact', updated_at = datetime('now') WHERE id = ?",
            (insight_id,),
        )
        conn.commit()
        conn.close()
        print(f"✅ Инсайт {insight_id} → artifact (importance={row['importance']})")
        return True
    finally:
        _flock_release()


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Управление инсайтами artifact-pulse")
    subparsers = parser.add_subparsers(dest="command")

    # add
    p_add = subparsers.add_parser("add", help="Добавить инсайт")
    p_add.add_argument("--content", required=True)
    p_add.add_argument("--source", required=True)
    p_add.add_argument("--type", required=True, dest="insight_type")
    p_add.add_argument(
        "--confidence", default="medium", choices=list(VALID_CONFIDENCE.keys())
    )
    p_add.add_argument("--context", default="")
    p_add.add_argument("--tags", default="")
    p_add.add_argument("--tool", default="")
    p_add.add_argument("--session-id", default="")
    p_add.add_argument("--agent-pair", default="")

    # list
    p_list = subparsers.add_parser("list", help="Список инсайтов")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--source", default=None)
    p_list.add_argument("--limit", type=int, default=20)

    # consolidate
    p_cons = subparsers.add_parser(
        "consolidate", help="Консолидация: new→verified→artifact"
    )
    p_cons.add_argument("--min-confidence", type=float, default=0.5)

    # stats
    subparsers.add_parser("stats", help="Статистика")

    # verify
    p_verify = subparsers.add_parser("verify", help="Подтвердить инсайт (new→verified)")
    p_verify.add_argument("--id", required=True)

    # promote
    p_promote = subparsers.add_parser("promote", help="Продвинуть verified→artifact")
    p_promote.add_argument("--id", required=True)

    args = parser.parse_args()

    if args.command == "add":
        add_insight(
            args.content,
            args.source,
            args.insight_type,
            args.confidence,
            args.context,
            args.tags,
            args.tool,
            args.session_id,
            args.agent_pair,
        )
    elif args.command == "list":
        list_insights(args.status, args.limit, args.source)
    elif args.command == "consolidate":
        consolidate(args.min_confidence)
    elif args.command == "stats":
        show_stats()
    elif args.command == "verify":
        verify_insight(args.id)
    elif args.command == "promote":
        promote_insight(args.id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
