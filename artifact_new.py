#!/usr/bin/env python3
"""
artifact_new.py — генератор шаблонов артефактов LabDoctorM.

Создаёт .md файл с корректным frontmatter:
- Автоматический ID (следующий свободный для типа)
- Дата создания/updated = сегодня
- Статус = draft
- confidence = high
- source = agent

Usage:
  python3 artifact_new.py --type pattern --title "High availability pattern" [--dir PATH] [--json]
  python3 artifact_new.py --type adr --title "Use Xray for VPN" [--dry-run]
"""

import sys
import json
import argparse
import re
from datetime import datetime, timezone
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import load_all_artifacts as _canonical_load_all
from artifact_constants import (
    TYPE_PREFIX,
    VALID_STATUSES,
)

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()

VALID_TYPES = sorted(TYPE_PREFIX.keys())


def _get_existing_ids(artifacts: dict, prefix: str) -> list[int]:
    """Extract all existing numeric IDs for a given prefix."""
    ids = []
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    for aid in artifacts:
        m = pattern.match(aid)
        if m:
            ids.append(int(m.group(1)))
    return ids


def _next_id(prefix: str, existing_ids: list[int]) -> str:
    """Generate next available ID for a prefix."""
    next_num = (max(existing_ids) + 1) if existing_ids else 1
    return f"{prefix}-{next_num:03d}"


def generate_artifact(atype: str, title: str, dry_run: bool = False) -> dict:
    """Generate a new artifact with proper frontmatter."""
    if atype not in VALID_TYPES:
        return {"error": f"Invalid type '{atype}'. Valid: {VALID_TYPES}"}

    artifacts = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)
    prefix = TYPE_PREFIX[atype]
    existing_ids = _get_existing_ids(artifacts, prefix)
    aid = _next_id(prefix, existing_ids)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    initial_status = next(iter(VALID_STATUSES.get(atype, ["draft"])), "draft")

    # Build frontmatter dict
    frontmatter = {
        "id": aid,
        "type": atype,
        "title": title,
        "status": initial_status,
        "author": "ЗавЛаб",
        "created": now,
        "updated": now,
        "confidence": "high",
        "source": "agent",
        "tags": [],
    }

    # Determine file path from config
    type_dir = ARTIFACT_DIRS.get(atype)
    if not type_dir:
        return {"error": f"No directory configured for type '{atype}'"}

    fpath = type_dir / f"{aid}.md"

    if fpath.exists():
        return {"error": f"File already exists: {fpath.relative_to(LAB_DIR)}"}

    # Build markdown content
    lines = ["---"]
    import yaml
    buf = __import__("io").StringIO()
    yaml.dump(frontmatter, buf, default_flow_style=False, allow_unicode=True, sort_keys=False)
    lines.append(buf.getvalue().strip())
    lines.extend(["---", "", f"# {aid}: {title}", ""])
    content = "\n".join(lines) + "\n"

    if not dry_run:
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")

    return {
        "id": aid,
        "file": str(fpath.relative_to(LAB_DIR)),
        "type": atype,
        "title": title,
        "status": initial_status,
        "dry_run": dry_run,
    }


def format_result(result: dict) -> str:
    if "error" in result:
        return f"ERROR: {result['error']}"

    if result.get("dry_run"):
        fpath = result.get("file", "(not determined)")
        return f"[DRY-RUN] Would create: {result['id']} {result['title']}\n  File: {fpath}"
    else:
        return f"✅ Created: {result['id']} — {result['title']}\n   File: {result['file']}\n   Status: {result['status']}"


def main():
    parser = argparse.ArgumentParser(description="Generate new artifact template")
    parser.add_argument("--type", "-t", required=True, choices=VALID_TYPES, help="Artifact type")
    parser.add_argument("--title", required=True, help="Artifact title")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to disk")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    result = generate_artifact(args.type, args.title, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_result(result))

    sys.exit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()
