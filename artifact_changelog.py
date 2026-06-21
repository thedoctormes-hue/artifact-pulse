#!/usr/bin/env python3
"""
artifact_changelog.py — версионирование и changelog артефактов LabDoctorM.

Хранит историю изменений каждого артефакта в frontmatter (history field)
и генерирует общий CHANGELOG.md.

Usage:
  python3 artifact_changelog.py <artifact_id> [--show] [--add "change description"]
  python3 artifact_changelog.py --generate-changelog [--since DAYS]
  python3 artifact_changelog.py --audit
"""

import sys
import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from config_loader import get_lab_dir, get_artifact_dirs, get_state_file
from artifact_core import parse_frontmatter_with_raw, load_all_artifacts as _canonical_load_all

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()
CHANGELOG_FILE = get_state_file("changelog") or LAB_DIR / "ARTIFACT_CHANGELOG.md"
TEMPLATE_NAMES = {"template", "шаблон", "readme"}


def rebuild_frontmatter(metadata: dict) -> str:
    """Rebuild frontmatter string from metadata dict."""
    lines = ["---"]
    for key, value in metadata.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            items = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{items}]")
        elif isinstance(value, str) and (" " in value or ":" in value):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def find_artifact(artifact_id: str) -> tuple[Path, dict, str, str] | None:
    """Find artifact by ID. Returns (path, metadata, body, raw_fm) or None."""
    artifacts = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)
    if artifact_id not in artifacts:
        return None
    art = artifacts[artifact_id]
    fpath = art["fpath"]
    content = art["full_content"]
    meta, body, raw_fm = parse_frontmatter_with_raw(content)
    return fpath, meta, body, raw_fm


def add_history_entry(artifact_id: str, change: str):
    """Add a history entry to an artifact."""
    result = find_artifact(artifact_id)
    if not result:
        print(f"ERROR: artifact {artifact_id} not found")
        sys.exit(1)

    fpath, meta, body, raw_fm = result

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = meta.get("history", [])
    if isinstance(history, str):
        history = [history]

    entry = f"{now}: {change}"
    history.append(entry)

    # Keep last 20 entries
    history = history[-20:]
    meta["history"] = history
    meta["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # Rebuild file
    new_fm = rebuild_frontmatter(meta)
    new_content = f"{new_fm}\n\n{body}"
    fpath.write_text(new_content, encoding="utf-8")
    print(f"Updated {fpath.relative_to(LAB_DIR)}: added history entry")
    print(f"  → {entry}")


def show_history(artifact_id: str):
    """Show history of an artifact."""
    result = find_artifact(artifact_id)
    if not result:
        print(f"ERROR: artifact {artifact_id} not found")
        sys.exit(1)

    fpath, meta, body, raw_fm = result

    print(f"═══ {artifact_id}: {meta.get('title', '?')} ═══")
    print(f"File: {fpath.relative_to(LAB_DIR)}")
    print(f"Status: {meta.get('status', '?')}")
    print(f"Created: {meta.get('created', '?')}")
    print(f"Updated: {meta.get('updated', '?')}")

    history = meta.get("history", [])
    if isinstance(history, str):
        history = [history]

    if history:
        print(f"\nHistory ({len(history)} entries):")
        for entry in history:
            print(f"  • {entry}")
    else:
        print("\nNo history entries.")

    # Show git log for this file
    print("\nGit history:")
    os.system(f"cd {LAB_DIR} && git log --oneline -5 -- '{fpath.relative_to(LAB_DIR)}' 2>/dev/null || echo '  (no git history)'")


def generate_changelog(since_days: int = 30):
    """Generate ARTIFACT_CHANGELOG.md with recent changes."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)

    artifacts = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)
    entries = []

    for aid, art in artifacts.items():
        meta = art["meta"]
        updated = meta.get("updated", meta.get("created", ""))
        if not updated:
            continue

        try:
            updated_dt = datetime.fromisoformat(updated.replace("+00:00", "+00:00"))
            if updated_dt < since:
                continue
        except (ValueError, TypeError):
            continue

        history = meta.get("history", [])
        if isinstance(history, str):
            history = [history]

        entries.append(
            {
                "updated": updated,
                "id": aid,
                "title": art["title"],
                "type": art["type"],
                "status": art["status"],
                "file": art["file"],
                "history": history,
            }
        )

    # Sort by updated date descending
    entries.sort(key=lambda x: x["updated"], reverse=True)

    # Generate markdown
    lines = [
        "# ARTIFACT CHANGELOG",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Period: last {since_days} days",
        f"Total changes: {len(entries)}",
        "",
        "---",
        "",
    ]

    for e in entries:
        lines.append(f"## {e['id']}: {e['title']}")
        lines.append("")
        lines.append(f"- **Type:** {e['type']} | **Status:** {e['status']}")
        lines.append(f"- **Updated:** {e['updated']}")
        lines.append(f"- **File:** `{e['file']}`")

        if e["history"]:
            lines.append("- **Changes:**")
            for h in e["history"][-5:]:  # last 5
                lines.append(f"  - {h}")

        lines.append("")

    CHANGELOG_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Changelog generated: {CHANGELOG_FILE}")
    print(f"  {len(entries)} changes in last {since_days} days")


def audit_artifacts():
    """Audit all artifacts for consistency."""
    issues = []
    artifacts = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)
    total = len(artifacts)

    for aid, art in artifacts.items():
        meta = art["meta"]
        fpath_name = art["file"].split("/")[-1]

        if not meta.get("id"):
            issues.append((fpath_name, "Missing id"))

        if not meta.get("title"):
            issues.append((fpath_name, "Missing title"))

        if not meta.get("status"):
            issues.append((fpath_name, "Missing status"))

        if not meta.get("updated"):
            issues.append((fpath_name, "Missing updated"))

        # Check body not empty
        if len(art["body"].strip()) < 20:
            issues.append((fpath_name, f"Body too short ({len(art['body'].strip())} chars)"))

    print(f"Audit: {total} artifacts checked, {len(issues)} issues")
    for fname, issue in issues:
        print(f"  ⚠️  {fname}: {issue}")

    if not issues:
        print("  ✅ All artifacts valid")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if args[0] == "--generate-changelog":
        since = 30
        for i, a in enumerate(args):
            if a == "--since" and i + 1 < len(args):
                since = int(args[i + 1])
        generate_changelog(since)

    elif args[0] == "--audit":
        audit_artifacts()

    else:
        artifact_id = args[0]

        if "--show" in args:
            show_history(artifact_id)
        elif "--add" in args:
            idx = args.index("--add")
            if idx + 1 < len(args):
                change = args[idx + 1]
                add_history_entry(artifact_id, change)
            else:
                print("ERROR: --add requires a description")
                sys.exit(1)
        else:
            show_history(artifact_id)


if __name__ == "__main__":
    main()
