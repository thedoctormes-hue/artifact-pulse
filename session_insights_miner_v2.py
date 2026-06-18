#!/usr/bin/env python3
"""
Session Insights Miner v2 — рефакторинг с семантическим дедупом через bge-m3.

Ключевые изменения v1→v2:
- subprocess → прямой вызов add_insights() (убирает race condition)
- Семантический дедуп через Ollama bge-m3 (cosine similarity > 0.85)
- Батч-эмбеддинг: один проход для всех кандидатов сессии
- flock через artifact_insights.py save_queue()
- sessionID + agent_pair в каждом инсайте
"""

import json
import hashlib
import re
import sys
import math
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set, Tuple

# ── Add project root to path for direct import ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from artifact_insights import add_insight, load_queue


def _md5_hash(text: str) -> str:
    """MD5 hash used for deduplication (same as original miner)."""
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


# ── Configuration ──────────────────────────────────────────────────────────────
OPENCLAW_SESSIONS_BASE = Path("/root/.openclaw/agents")
MAX_SESSION_AGE_HOURS = 48
MIN_CONTENT_LENGTH = 120
MAX_INSIGHTS_PER_SESSION = 3
MIN_INSIGHT_SCORE = 2
MIN_INSIGHT_SCORE_SECURITY = 1
SEMANTIC_DUP_THRESHOLD = 0.85

# ── Ollama bge-m3 ────────────────────────────────────────────────────────────
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3"


def get_embedding(text: str) -> List[float]:
    """Get embedding from Ollama bge-m3. Returns [] on failure."""
    try:
        data = json.dumps({"model": EMBED_MODEL, "prompt": text[:512]}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return result.get("embedding", [])
    except Exception:
        return []


def cosine_sim(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def batch_embeddings(texts: List[str]) -> List[List[float]]:
    """Get embeddings for multiple texts. Returns list of vectors (empty on failure)."""
    return [get_embedding(t) for t in texts]


def semantic_dedup_batch(
    candidates: List[Tuple[str, str, str, str]],
    existing_embeddings: List[Tuple[str, List[float]]],
) -> List[Tuple[str, str, str, str]]:
    """
    Semantic dedup: filter candidates that are too similar to existing insights.
    candidates: list of (content, source, itype, tags)
    existing_embeddings: list of (content, embedding_vector)
    Returns filtered candidates.
    """
    if not candidates or not existing_embeddings:
        return candidates

    # Get embeddings for all candidates
    cand_texts = [c[0][:512] for c in candidates]
    cand_vecs = batch_embeddings(cand_texts)

    filtered = []
    for i, (content, source, itype, tags) in enumerate(candidates):
        vec = cand_vecs[i]
        if not vec:
            # No embedding — keep candidate (will be deduped by MD5 later)
            filtered.append((content, source, itype, tags))
            continue

        is_dup = False
        for _, evec in existing_embeddings:
            if evec and cosine_sim(vec, evec) >= SEMANTIC_DUP_THRESHOLD:
                is_dup = True
                break

        if not is_dup:
            filtered.append((content, source, itype, tags))

    return filtered


# ── Insight patterns ───────────────────────────────────────────────────────────
SECURITY_PATTERNS = [
    r"(?i)(security|vulnerability|exposure|leak|token|key|password|secret|безопасность|уязвимость|утечка)",
    r"(?i)(важно|attention|warning|danger|risk|риск|опасно|критично)",
]

INSIGHT_PATTERNS = [
    r"(?i)(error|failed|failure|exception|bug|issue|problem|broken|doesn'?t work|not working)",
    r"(?i)(discovered|found|realized|noticed|see that|turns out|it appears|выяснил|обнаружил)",
    r"(?i)(decided|will|should|going to|plan to|need to|have to|решил|нужно|следует)",
    r"(?i)(pattern|trend|common|always|usually|typically|every time|паттерн|закономерность)",
    r"(?i)(fixed|solved|resolved|workaround|solution|fix|patch|исправил|починил)",
    r"(?i)(learned|understood|now i know|insight|takeaway|lesson|понял|узнал)",
    r"(?i)(security|vulnerability|exposure|leak|token|key|password|secret|безопасность|уязвимость|утечка)",
    r"(?i)(slow|fast|performance|latency|timeout|optimization|производительность|оптимизация)",
    r"(?i)(важно|attention|warning|danger|risk|риск|опасно|критично)",
    r"(?i)(рекомендация|advice|best practice|guideline|рекомендую|советую)",
]


def is_security_insight(text: str) -> bool:
    return any(re.search(p, text) for p in SECURITY_PATTERNS)


def score_insight(text: str) -> Tuple[int, List[str]]:
    score = 0
    matched = []
    for pattern in INSIGHT_PATTERNS:
        if re.search(pattern, text):
            score += 1
            matched.append(pattern)
    return score, matched


def classify_type(text: str) -> str:
    if re.search(
        r"(?i)(error|failed|failure|exception|bug|broken|doesn.?t work|not working)",
        text,
    ):
        return "error"
    if re.search(
        r"(?i)(pattern|trend|common|always|usually|паттерн|закономерность)", text
    ):
        return "pattern"
    if re.search(r"(?i)(decided|will|should|plan to|решил|нужно|следует)", text):
        return "decision"
    return "finding"


# ── Session scanning ──────────────────────────────────────────────────────────
def find_recent_session_files() -> List[Path]:
    cutoff = datetime.now() - timedelta(hours=MAX_SESSION_AGE_HOURS)
    files = []
    if not OPENCLAW_SESSIONS_BASE.exists():
        return files
    for agent_dir in OPENCLAW_SESSIONS_BASE.iterdir():
        if not agent_dir.is_dir():
            continue
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.exists():
            continue
        for traj in sessions_dir.glob("*.trajectory.jsonl"):
            try:
                if datetime.fromtimestamp(traj.stat().st_mtime) >= cutoff:
                    files.append(traj)
            except (OSError, ValueError):
                continue
    return sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)


def extract_assistant_texts(traj_file: Path) -> List[str]:
    texts = []
    try:
        with open(traj_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "model.completed":
                    continue
                data = record.get("data", {})
                msgs = data.get("messagesSnapshot", [])
                for msg in msgs:
                    if msg.get("role") != "assistant":
                        continue
                    text = msg.get("summary") or ""
                    if not text:
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            parts = []
                            for part in content:
                                if (
                                    isinstance(part, dict)
                                    and part.get("type") == "text"
                                ):
                                    parts.append(part.get("text", ""))
                            text = " ".join(parts)
                        elif isinstance(content, str):
                            text = content
                    if text and len(text) >= MIN_CONTENT_LENGTH:
                        texts.append(text)
    except Exception as e:
        print(f"  ⚠ Error reading {traj_file}: {e}", file=sys.stderr)
    return texts


def process_session(
    traj_file: Path,
    existing_hashes: Set[str],
    existing_embeddings: List[Tuple[str, List[float]]],
) -> int:
    """Process one session file with semantic dedup. Returns new insights count."""
    agent_name = traj_file.parent.name
    session_id = traj_file.stem.replace(".trajectory", "")
    texts = extract_assistant_texts(traj_file)
    if not texts:
        return 0

    # Phase 1: Score and filter candidates
    candidates = []
    seen_in_session: Set[str] = set()

    for text in texts:
        h = _md5_hash(text)
        if h in existing_hashes or h in seen_in_session:
            continue

        score, matched = score_insight(text)

        if is_security_insight(text):
            if score < MIN_INSIGHT_SCORE_SECURITY:
                continue
            itype = "security"
        else:
            if score < MIN_INSIGHT_SCORE:
                continue
            itype = classify_type(text)

        snippet = text[:400].strip()
        if len(text) > 400:
            snippet += "..."

        tags = f"session-mining,{agent_name}"
        if itype == "security":
            tags += ",security"

        candidates.append((snippet, agent_name, itype, tags))
        seen_in_session.add(h)

    if not candidates:
        return 0

    # Phase 2: Semantic dedup (batch)
    filtered = semantic_dedup_batch(candidates, existing_embeddings)

    # Phase 3: Add insights (direct call, no subprocess)
    added = 0
    for content, source, itype, tags in filtered:
        result = add_insight(
            content=content,
            source=source,
            insight_type=itype,
            confidence="medium",
            context=f"session-mining-{source}",
            tags=tags,
            session_id=session_id,
            agent_pair=f"{agent_name}-session",
        )
        if result:
            added += 1
            existing_hashes.add(_md5_hash(content))
            print(f"  ✓ [{itype}] {content[:100]}...")

        if added >= MAX_INSIGHTS_PER_SESSION:
            break

    return added


def main():
    print("🔍 Session Insights Miner v2 (bge-m3 semantic dedup)")
    print(f"   Scanning: {OPENCLAW_SESSIONS_BASE}")
    print(f"   Age limit: {MAX_SESSION_AGE_HOURS}h")
    print(f"   Semantic threshold: {SEMANTIC_DUP_THRESHOLD}")
    print()

    # Load existing queue for dedup
    queue = load_queue()
    existing_hashes: Set[str] = set()
    existing_embeddings: List[Tuple[str, List[float]]] = []

    for ins in queue.get("insights", []):
        h = _md5_hash(ins.get("content", ""))
        existing_hashes.add(h)
        # Try to get cached embedding
        cached = ins.get("embedding")
        if cached and isinstance(cached, list):
            existing_embeddings.append((ins["content"], cached))

    print(
        f"📊 Queue: {len(queue.get('insights', []))} insights, {len(existing_embeddings)} with embeddings"
    )

    session_files = find_recent_session_files()
    print(f"📁 {len(session_files)} session files found")
    print()

    total_added = 0
    sessions_with_insights = 0

    for traj_file in session_files:
        rel = traj_file.relative_to(OPENCLAW_SESSIONS_BASE)
        print(f"🔎 {rel} ...", end=" ", flush=True)

        n = process_session(traj_file, existing_hashes, existing_embeddings)
        if n > 0:
            print(f"→ {n} insight(s)")
            total_added += n
            sessions_with_insights += 1
        else:
            print("→ 0")

    print()
    print(f"📊 Done: {total_added} new insights from {sessions_with_insights} sessions")

    # Show stats
    from artifact_insights import show_stats

    show_stats()

    return 0


if __name__ == "__main__":
    sys.exit(main())
