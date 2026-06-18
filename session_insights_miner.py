#!/usr/bin/env python3
"""
Session Insights Miner for OpenClaw
Automatically extracts insights from agent session transcripts (trajectory.jsonl files)
and adds them to the artifact pulse system via artifact_insights.py.

Strategy:
- Scan all agent session trajectory files modified in the last N hours
- For each model.completed event, extract assistant text from messagesSnapshot
- Score each assistant message against insight patterns
- If score >= 1, add as insight to the queue
- Deduplicate: skip if same content hash already exists
"""

import json
import hashlib
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set
import subprocess
import os

# ── Context API ───────────────────────────────────────────────────────────────
CONTEXT_API_URL = "http://127.0.0.1:8100"
CONTEXT_API_KEY = os.environ.get("CONTEXT_API_KEY", "lab-internal-change-me")

# ── Configuration ──────────────────────────────────────────────────────────────
OPENCLAW_SESSIONS_BASE = Path("/root/.openclaw/agents")
INSIGHTS_SCRIPT = Path("/root/LabDoctorM/projects/artifact-pulse/artifact_insights.py")
INSIGHTS_QUEUE = Path("/root/LabDoctorM/.qwen/artifacts/insights_queue.json")
MAX_SESSION_AGE_HOURS = 48
MIN_CONTENT_LENGTH = 120  # minimum chars to consider
MAX_INSIGHTS_PER_SESSION = 3  # cap per session to avoid flooding
MIN_INSIGHT_SCORE = 2  # at least 2 pattern matches required
MIN_INSIGHT_SCORE_SECURITY = 1  # security patterns: lower threshold

# ── Security patterns (high priority, lower threshold) ──────────────────────
SECURITY_PATTERNS = [
    r"(?i)(security|vulnerability|exposure|leak|token|key|password|secret|безопасность|уязвимость|утечка)",
    r"(?i)(важно|attention|warning|danger|risk|риск|опасно|критично)",
]


def is_security_insight(text: str) -> bool:
    """Check if text matches security patterns."""
    return any(re.search(p, text) for p in SECURITY_PATTERNS)


# ── Insight patterns ───────────────────────────────────────────────────────────
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


def content_hash(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


def load_existing_hashes() -> Set[str]:
    """Load hashes of existing insights to avoid duplicates."""
    if not INSIGHTS_QUEUE.exists():
        return set()
    try:
        with open(INSIGHTS_QUEUE, "r", encoding="utf-8") as f:
            data = json.load(f)
        insights = (
            data
            if isinstance(data, list)
            else data.get("insights", data.get("queue", []))
        )
        return {
            content_hash(i.get("content", "")) for i in insights if isinstance(i, dict)
        }
    except Exception:
        return set()


def find_recent_session_files() -> List[Path]:
    """Find trajectory.jsonl files modified in the last N hours."""
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
    """Extract all assistant text snippets from a trajectory file."""
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
                    # Try summary first
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


def score_insight(text: str) -> tuple:
    """Return (score, matched_patterns)."""
    score = 0
    matched = []
    for pattern in INSIGHT_PATTERNS:
        if re.search(pattern, text):
            score += 1
            matched.append(pattern)
    return score, matched


def classify_type(text: str) -> str:
    """Classify insight type based on content."""
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


def add_insight(
    content: str,
    source: str,
    insight_type: str,
    tags: str,
    session_id: str = "",
    agent_pair: str = "",
) -> bool:
    """Call artifact_insights.py add with session_id and agent_pair."""
    try:
        cmd = [
            sys.executable,
            str(INSIGHTS_SCRIPT),
            "add",
            "--content",
            content,
            "--context",
            f"session-mining-{source}",
            "--source",
            source,
            "--type",
            insight_type,
            "--confidence",
            "medium",
            "--tags",
            tags,
        ]
        if session_id:
            cmd.extend(["--session-id", session_id])
        if agent_pair:
            cmd.extend(["--agent-pair", agent_pair])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(INSIGHTS_SCRIPT.parent),
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def process_session(traj_file: Path, existing_hashes: Set[str]) -> int:
    """Process one session file, return number of new insights added."""
    agent_name = traj_file.parent.name
    session_id = traj_file.stem.replace(".trajectory", "")
    texts = extract_assistant_texts(traj_file)
    if not texts:
        return 0

    added = 0
    seen_in_session: Set[str] = set()

    for text in texts:
        h = content_hash(text)
        if h in existing_hashes or h in seen_in_session:
            continue

        score, matched = score_insight(text)

        # Security mode: lower threshold for security patterns
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

        agent_pair = f"{agent_name}-session"

        if add_insight(
            content=snippet,
            source=agent_name,
            insight_type=itype,
            tags=tags,
            session_id=session_id,
            agent_pair=agent_pair,
        ):
            existing_hashes.add(h)
            seen_in_session.add(h)
            added += 1
            print(f"  ✓ [{itype}] {snippet[:100]}...")

        if added >= MAX_INSIGHTS_PER_SESSION:
            break

    return added


def main():
    print("🔍 Session Insights Miner")
    print(f"   Scanning: {OPENCLAW_SESSIONS_BASE}")
    print(f"   Age limit: {MAX_SESSION_AGE_HOURS}h")
    print()

    existing_hashes = load_existing_hashes()
    session_files = find_recent_session_files()
    print(f"📁 {len(session_files)} session files found")
    print(f"🔒 {len(existing_hashes)} existing insight hashes (dedup)")
    print()

    total_added = 0
    sessions_with_insights = 0

    for traj_file in session_files:
        rel = traj_file.relative_to(OPENCLAW_SESSIONS_BASE)
        print(f"🔎 {rel} ...", end=" ", flush=True)

        n = process_session(traj_file, existing_hashes)
        if n > 0:
            print(f" → {n} insight(s)")
            total_added += n
            sessions_with_insights += 1
        else:
            print("→ 0")

    print()
    print(f"📊 Done: {total_added} new insights from {sessions_with_insights} sessions")

    # Show stats
    try:
        subprocess.run(
            [sys.executable, str(INSIGHTS_SCRIPT), "stats"],
            cwd=str(INSIGHTS_SCRIPT.parent),
        )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
