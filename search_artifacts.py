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
import re
import json
import hashlib
from datetime import datetime
from config_loader import get_lab_dir, get_artifact_dirs, get_state_file
from artifact_core import load_all_artifacts as _canonical_load_all

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()
INDEX_FILE = get_state_file("search_index") or LAB_DIR / ".qwen/artifacts/search_index.json"


def build_index() -> dict:
    """Build search index from all artifacts. Returns index dict."""
    mtime, count = _dir_fingerprint()
    artifacts = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)

    index = {
        "built_at": datetime.now().isoformat(),
        "total": len(artifacts),
        "dir_mtime": mtime,
        "dir_count": count,
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


def _dir_fingerprint() -> tuple[float, int]:
    """Return (max_mtime, file_count) across all artifact dirs — O(directories) not O(files)."""
    max_mtime = 0.0
    count = 0
    for d in ARTIFACT_DIRS:
        p = LAB_DIR / d
        if not p.is_dir():
            continue
        for f in p.rglob("*.md"):
            try:
                st = f.stat()
                max_mtime = max(max_mtime, st.st_mtime)
                count += 1
            except OSError:
                pass
    return max_mtime, count


def load_index() -> dict:
    """Load index from disk, rebuild if stale (O(directories) fingerprint, not O(files))."""
    if INDEX_FILE.exists():
        try:
            index = json.loads(INDEX_FILE.read_text())
            if index.get("total", 0) > 0 and index.get("dir_mtime") is not None:
                cur_mtime, cur_count = _dir_fingerprint()
                if cur_mtime == index["dir_mtime"] and cur_count == index.get("dir_count", 0):
                    return index
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Rebuild
    index = build_index()
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    return index


def load_artifacts() -> list:
    """Load all artifacts from all directories."""
    raw = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)
    return list(raw.values())


def _score_terms(entry: dict, query_words: list[str], title: str, body_words: set, tags_str: str, aid: str) -> float:
    """Shared scoring logic for index entries and artifact dicts."""
    score = 0.0
    for word in query_words:
        word_lower = word.lower()
        if word_lower in title:
            score += 10.0
        if word_lower in tags_str:
            score += 8.0
        if word_lower in body_words:
            score += 3.0
        if word_lower == aid.lower():
            score += 50.0
    score += entry.get("confirmations", 0) * 2.0
    status = str(entry.get("status", "")).lower()
    if status == "draft":
        score *= 0.7
    elif status in ("deprecated", "rejected", "archived"):
        score *= 0.3
    elif status == "stale":
        score *= 0.5
    return score


def score_artifact(artifact: dict, query_words: list[str]) -> float:
    """Score artifact relevance to query. Higher = more relevant."""
    title = str(artifact.get("title", "")).lower()
    tags = artifact.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    tags_str = " ".join(str(t).lower() for t in tags)

    # Build body words set from body
    body = artifact.body.lower()
    body_words = set(re.findall(r"[a-zA-Zа-яёА-ЯЁ]{3,}", body))

    entry = {
        "status": artifact.get("status", ""),
        "confirmations": int(artifact.get("confirmations", 0) or 0),
    }
    return _score_terms(entry, query_words, title, body_words, tags_str, str(artifact.get("id", "")))


def score_index_entry(entry: dict, query_words: list[str]) -> float:
    """Score index entry relevance to query."""
    title = entry.get("title", "").lower()
    body_words = set(entry.get("words", []))
    tags = entry.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    tags_str = " ".join(str(t).lower() for t in tags)

    score = _score_terms(entry, query_words, title, body_words, tags_str, str(entry.get("id", "")))

    # Bonus: title_words pre-tokenized match (index-specific optimization)
    title_words = set(entry.get("title_words", []))
    for word in query_words:
        if word.lower() in title_words:
            score += 2.0  # small bonus for pre-tokenized title match

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
