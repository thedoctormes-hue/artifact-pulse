#!/usr/bin/env python3
"""
provenance_patch.py — массовое добавление source и last_verified в frontmatter артефактов.

Правила:
- Активные артефакты (status NOT IN archived/rejected/closed/resolved/done/deprecated):
  - Добавляются source и last_verified
- Авторы-агенты (owl, kotolizator, bestia, mangust, streikbrecher, antcat, Сова, Бестия, Мангуст, Ворон, Доминика, Штрейкбрехер, КотОлизатор):
  - source: agent
- Остальные (system, ЗавЛаб, root, пусто):
  - source: manual
- Неактивные артефакты — пропускаются
- Шаблоны (id/template в имени) — пропускаются
"""

import re
import sys
from pathlib import Path

LAB_DIR = Path("/root/LabDoctorM")
ARTIFACT_DIRS = [
    LAB_DIR / "patterns",
    LAB_DIR / "adr",
    LAB_DIR / "rules",
    LAB_DIR / "specs",
    LAB_DIR / "incidents",
]

# Статусы, при которых артефакт считается НЕактивным
INACTIVE_STATUSES = {"archived", "rejected", "closed", "resolved", "done", "deprecated"}

# Авторы-агенты → source: agent
AGENT_AUTHORS = {
    "owl",
    "kotolizator",
    "bestia",
    "mangust",
    "streikbrecher",
    "antcat",
    "сова",
    "бестия",
    "мангуст",
    "ворон",
    "доминика",
    "штрейкбрехер",
    "котолизator",
    "raven",
    "dominika",
}

TODAY = "2026-06-17"


def parse_frontmatter(content: str) -> tuple[dict, int, int] | None:
    """Parse YAML frontmatter, return (fields, start_pos, end_pos)."""
    if not content.startswith("---"):
        return None

    # Find end of frontmatter
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return None

    end_pos = 3 + end_match.end()
    fm_text = content[3 : 3 + end_match.start()]

    # Simple key: value parser (no nested structures)
    fields = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            fields[key] = val

    return fields, 0, end_pos


def is_active(status: str) -> bool:
    """Check if artifact status is active."""
    return status.lower().strip() not in INACTIVE_STATUSES


def get_source(author: str) -> str:
    """Determine source field from author."""
    if not author:
        return "manual"
    author_lower = author.lower().strip()
    if author_lower in AGENT_AUTHORS:
        return "agent"
    return "manual"


def patch_file(fpath: Path) -> dict:
    """Add source and last_verified to frontmatter if missing. Returns result dict."""
    content = fpath.read_text(encoding="utf-8")

    parsed = parse_frontmatter(content)
    if parsed is None:
        return {"file": str(fpath), "action": "skip", "reason": "no frontmatter"}

    fields, _, end_pos = parsed
    status = fields.get("status", "")
    author = fields.get("author", "")

    # Skip inactive
    if status and not is_active(status):
        return {"file": str(fpath), "action": "skip", "reason": f"inactive ({status})"}

    # Skip templates
    aid = fields.get("id", "")
    if "template" in aid.lower() or "template" in fpath.name.lower():
        return {"file": str(fpath), "action": "skip", "reason": "template"}

    has_source = "source" in fields
    has_verified = "last_verified" in fields

    if has_source and has_verified:
        return {
            "file": str(fpath),
            "action": "skip",
            "reason": "already has both fields",
        }

    # Determine what to add
    source_val = fields.get("source", get_source(author))
    if not has_source and not fields.get("source"):
        source_val = get_source(author)

    # Build new frontmatter
    # We need to insert source and last_verified before the closing ---
    fm_text = content[3 : end_pos - 4]  # between --- and ---

    additions = []
    if not has_source:
        additions.append(f"source: {source_val}")
    if not has_verified:
        additions.append(f"last_verified: {TODAY}")

    if not additions:
        return {"file": str(fpath), "action": "skip", "reason": "nothing to add"}

    # Add fields at end of frontmatter (before closing ---)
    new_fm = fm_text.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
    new_content = "---\n" + new_fm + "---" + content[end_pos:]

    fpath.write_text(new_content, encoding="utf-8")

    return {
        "file": str(fpath.relative_to(LAB_DIR)),
        "action": "patched",
        "source": source_val,
        "status": status,
        "author": author,
    }


def main():
    results = []
    patched = 0
    skipped = 0
    errors = 0

    for dir_path in ARTIFACT_DIRS:
        if not dir_path.exists():
            print(f"WARNING: Directory not found: {dir_path}", file=sys.stderr)
            continue

        for fpath in sorted(dir_path.glob("*.md")):
            # Skip README, UPGRADE, templates by filename
            if fpath.name in ("README.md", "UPGRADE_PROMPT.md"):
                continue
            if "template" in fpath.name.lower():
                continue

            try:
                result = patch_file(fpath)
                results.append(result)
                if result["action"] == "patched":
                    patched += 1
                else:
                    skipped += 1
            except Exception as e:
                errors += 1
                results.append(
                    {"file": str(fpath), "action": "error", "reason": str(e)}
                )

    # Summary
    print(f"\n{'='*60}")
    print("PROVENANCE PATCH RESULTS")
    print(f"{'='*60}")
    print(f"Patched:  {patched}")
    print(f"Skipped:  {skipped}")
    print(f"Errors:   {errors}")
    print(f"Total:    {patched + skipped + errors}")

    # Show patched files
    if patched > 0:
        print("\n--- PATCHED FILES ---")
        for r in results:
            if r["action"] == "patched":
                print(
                    f"  ✅ {r['file']}  source={r['source']}  status={r['status']}  author={r['author']}"
                )

    # Show skipped inactive
    inactive = [r for r in results if r.get("reason", "").startswith("inactive")]
    if inactive:
        print(f"\n--- SKIPPED INACTIVE ({len(inactive)}) ---")
        for r in inactive:
            print(f"  ⏭  {r['file']}  ({r['reason']})")

    if errors > 0:
        print("\n--- ERRORS ---")
        for r in results:
            if r["action"] == "error":
                print(f"  ❌ {r['file']}: {r['reason']}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
