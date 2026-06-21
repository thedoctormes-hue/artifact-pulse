#!/usr/bin/env python3
"""
search_artifacts.py — полнотекстовый поиск по артефактам LabDoctorM.

Индексирует все .md файлы в артефактных директориях (patterns, adr, rules,
specs, incidents, metrics), поддерживает поиск по содержимому, фильтрацию по
типу/статусу/тегам, ранжирование по релевантности.

Usage:
  python3 search_artifacts.py <query> [--type TYPE] [--status STATUS] [--tag TAG] [--limit N] [--json]

Examples:
  python3 search_artifacts.py "auth middleware"
  python3 search_artifacts.py "docker" --type pattern
  python3 search_artifacts.py "VPN" --status active --limit 5
  python3 search_artifacts.py "тестирование" --json
"""

import sys
import os
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
from config_loader import get_lab_dir, get_artifact_dirs, get_state_file
from artifact_core import parse_frontmatter, load_all_artifacts as _canonical_load_all

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()
INDEX_FILE = get_state_file("search_index") or LAB_DIR / ".qwen/artifacts/search_index.json"
TEMPLATE_NAMES = {"template", "шаблон", "readme"}


def build_index() -> dict:
    """Build search index from all artifacts. Returns index dict."""
    artifacts = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)

    index = {
        "built_at": datetime.now().isoformat(),
        "total": len(artifacts),
        "entries": {},
    }

    for aid, art in artifacts.items():
        meta = art["meta"]
        body = art["body"]
        fpath = art["fpath"]

        title = str(meta.get("title", ""))
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        status = str(meta.get("status", ""))

        # Tokenize body for full-text search
        words = set(re.findall(r"[a-zA-Zа-яёА-ЯЁ]{3,}", body.lower()))
        title_words = set(re.findall(r"[a-zA-Zа-яёА-ЯЁ]{3,}", title.lower()))

        mtime = fpath.stat().st_mtime if fpath.exists() else 0
        file_hash = hashlib.md5(art["full_content"].encode()).hexdigest()

        index["entries"][aid] = {
            "id": aid,
            "type": art["type"],
            "title": title,
            "status": status,
            "tags": tags,
            "file": art["file"],
            "words": list(words),
            "title_words": list(title_words),
            "mtime": mtime,
            "hash": file_hash,
            "size": len(body),
            "confirmations": int(meta.get("confirmations", 0) or 0),
        }

    return index


def load_index() -> dict:
    """Load index from disk, rebuild if stale."""
    if INDEX_FILE.exists():
        try:
            index = json.loads(INDEX_FILE.read_text())
            # Check if any artifact file changed since index build
            stale = False
            for aid, entry in index.get("entries", {}).items():
                fpath = LAB_DIR / entry["file"]
                if not fpath.exists():
                    stale = True
                    break
                if fpath.stat().st_mtime != entry.get("mtime", 0):
                    stale = True
                    break
            if not stale and index.get("total", 0) > 0:
                return index
        except (json.JSONDecodeError, KeyError):
            pass

    # Rebuild
    index = build_index()
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    return index


def load_artifacts() -> list[dict]:
    """Load all artifacts from all directories."""
    raw = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)
    artifacts = []
    for aid, art in raw.items():
        meta = dict(art["meta"])
        meta["_file"] = art["file"]
        meta["_body"] = art["body"]
        meta["_size"] = len(art["body"])
        artifacts.append(meta)
    return artifacts


def score_artifact(artifact: dict, query_words: list[str]) -> float:
    """Score artifact relevance to query. Higher = more relevant."""
    score = 0.0
    title = str(artifact.get("title", "")).lower()
    body = artifact.get("_body", "").lower()
    tags = artifact.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    tags_str = " ".join(str(t).lower() for t in tags)

    for word in query_words:
        word_lower = word.lower()

        # Exact title match = highest score
        if word_lower in title:
            score += 10.0

        # Tag match = high score
        if word_lower in tags_str:
            score += 8.0

        # Body match = base score
        count = body.count(word_lower)
        if count > 0:
            score += min(count * 2.0, 20.0)  # cap at 20 per word

        # ID match (exact)
        aid = str(artifact.get("id", "")).lower()
        if word_lower == aid:
            score += 50.0

    # Boost by confirmations
    confirmations = int(artifact.get("confirmations", 0) or 0)
    score += confirmations * 2.0

    # Penalize drafts/deprecated
    status = str(artifact.get("status", "")).lower()
    if status == "draft":
        score *= 0.7
    elif status in ("deprecated", "rejected"):
        score *= 0.3

    return score


def score_index_entry(entry: dict, query_words: list[str]) -> float:
    """Score index entry relevance to query."""
    score = 0.0
    title = entry.get("title", "").lower()
    title_words = set(entry.get("title_words", []))
    body_words = set(entry.get("words", []))
    tags = entry.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    tags_str = " ".join(str(t).lower() for t in tags)

    for word in query_words:
        word_lower = word.lower()

        # Title word match
        if word_lower in title_words:
            score += 10.0
        elif word_lower in title:
            score += 8.0

        # Tag match
        if word_lower in tags_str:
            score += 8.0

        # Body word match
        if word_lower in body_words:
            score += 3.0

        # ID match (exact)
        aid = entry.get("id", "").lower()
        if word_lower == aid:
            score += 50.0

    # Boost by confirmations
    score += entry.get("confirmations", 0) * 2.0

    # Penalize drafts/deprecated/archived
    status = str(entry.get("status", "")).lower()
    if status == "draft":
        score *= 0.7
    elif status in ("deprecated", "rejected", "archived"):
        score *= 0.3
    elif status == "stale":
        score *= 0.5

    return score


def search(
    query: str,
    artifact_type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    limit: int = 10,
    json_output: bool = False,
    rebuild_index: bool = False,
):
    """Main search function. Uses persistent index for fast lookups."""
    if rebuild_index or not INDEX_FILE.exists():
        index = build_index()
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    else:
        index = load_index()

    entries = index.get("entries", {})

    # Pre-filter by structured fields
    filtered = {}
    for aid, entry in entries.items():
        if artifact_type and str(entry.get("type", "")).lower() != artifact_type.lower():
            continue
        if status and str(entry.get("status", "")).lower() != status.lower():
            continue
        if tag:
            tags = entry.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            if not any(tag.lower() in str(t).lower() for t in tags):
                continue
        filtered[aid] = entry

    # Score by query
    query_words = query.split()
    if not query_words:
        results = [(0.0, e) for e in filtered.values()]
    else:
        results = [(score_index_entry(e, query_words), e) for e in filtered.values()]

    # Sort by score descending
    results.sort(key=lambda x: x[0], reverse=True)

    # Filter zero-score
    results = [(s, e) for s, e in results if s > 0]

    # Limit
    results = results[:limit]

    if json_output:
        output = []
        for score, e in results:
            output.append(
                {
                    "score": round(score, 1),
                    "id": e.get("id", "?"),
                    "type": e.get("type", "?"),
                    "title": e.get("title", "?"),
                    "status": e.get("status", "?"),
                    "tags": e.get("tags", []),
                    "file": e.get("file", "?"),
                    "confirmations": e.get("confirmations", 0),
                }
            )
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if not results:
            print(f"No artifacts found for: '{query}'")
            if artifact_type:
                print(f"  (type filter: {artifact_type})")
            if status:
                print(f"  (status filter: {status})")
            return

        print(f"Found {len(results)} artifacts for: '{query}' (index: {index['total']} entries)")
        print()

        for score, e in results:
            aid = e.get("id", "?")
            title = e.get("title", "?")
            atype = e.get("type", "?")
            astatus = e.get("status", "?")
            tags = e.get("tags", [])
            confirmations = e.get("confirmations", 0)
            fpath = e.get("file", "?")

            tag_display = ", ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
            print(f"  [{score:5.1f}] {aid:<12} | {atype:<10} | {astatus:<10} | {title}")
            print(f"          tags: {tag_display} | conf: {confirmations} | {fpath}")
            print()


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    query = args[0]
    artifact_type = None
    status = None
    tag = None
    limit = 10
    json_output = False
    rebuild_index = False

    i = 1
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            artifact_type = args[i + 1]
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]
            i += 2
        elif args[i] == "--tag" and i + 1 < len(args):
            tag = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--json":
            json_output = True
            i += 1
        elif args[i] == "--rebuild-index":
            rebuild_index = True
            i += 1
        else:
            i += 1

    search(query, artifact_type, status, tag, limit, json_output, rebuild_index)


if __name__ == "__main__":
    main()
