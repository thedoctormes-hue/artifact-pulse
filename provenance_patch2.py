#!/usr/bin/env python3
"""
provenance_patch2.py — добивка артефактов без стандартного frontmatter.

Обрабатывает:
1. Артефакты без frontmatter вообще (PAT-005, ADR-022, ADR-028, INC-без-фронтматтера)
2. Артефакты с пустым статусом — считаются активными
"""

import re
import sys
from pathlib import Path

LAB_DIR = Path("/root/LabDoctorM")
TODAY = "2026-06-17"

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


def get_source(author: str) -> str:
    if not author:
        return "manual"
    if author.lower().strip() in AGENT_AUTHORS:
        return "agent"
    return "manual"


def extract_field(text: str, field: str) -> str:
    """Extract a field value from text (frontmatter or body)."""
    # Try YAML frontmatter style
    m = re.search(rf"^{field}\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return ""


def has_frontmatter(content: str) -> bool:
    return content.startswith("---")


def patch_file(fpath: Path) -> dict:
    content = fpath.read_text(encoding="utf-8")
    rel = str(fpath.relative_to(LAB_DIR))

    # Skip templates
    if "template" in fpath.name.lower():
        return {"file": rel, "action": "skip", "reason": "template"}

    if not has_frontmatter(content):
        # No frontmatter at all — need to determine author from body and add full frontmatter
        # Try to extract author from body
        author = ""
        # Look for patterns like **Автор:** owl or **Автор инцидента:** owl
        m = re.search(r"\*\*Автор[^:]*:\*\*\s*(\S+)", content)
        if m:
            author = m.group(1).strip()
        # Also check for author: in body
        if not author:
            author = extract_field(content, "author")

        source = get_source(author)

        # Determine status from body
        status = ""
        m = re.search(r"\*\*Статус[^:]*:\*\*\s*(\S+)", content)
        if m:
            status = m.group(1).strip()

        # Determine id from filename
        aid = fpath.stem

        # Determine type from directory
        dir_type = {
            "patterns": "pattern",
            "adr": "adr",
            "rules": "rule",
            "specs": "backlog",
            "incidents": "incident",
        }.get(fpath.parent.name, "unknown")

        # Build frontmatter
        fm_lines = [
            f"type: {dir_type}",
            f"id: {aid}",
            f"title: {aid}",
            f"status: {status or 'active'}",
            f"author: {author or 'system'}",
            f"created: {TODAY}",
            f"updated: {TODAY}",
            f"source: {source}",
            f"last_verified: {TODAY}",
            f"tags: [{dir_type}]",
        ]

        new_content = "---\n" + "\n".join(fm_lines) + "\n---\n\n" + content
        fpath.write_text(new_content, encoding="utf-8")

        return {
            "file": rel,
            "action": "added_frontmatter",
            "source": source,
            "status": status,
        }

    return {"file": rel, "action": "skip", "reason": "has frontmatter"}


def main():
    files_to_patch = [
        LAB_DIR / "patterns/PAT-005-no-facts-without-proof.md",
        LAB_DIR / "adr/ADR-022-monorepo-strategy.md",
        LAB_DIR / "adr/ADR-028-openclaw-json-agent-registry.md",
        LAB_DIR / "incidents/INC-2026-06-16-001.md",
        LAB_DIR / "incidents/INC-2026-06-17-001.md",
    ]

    results = []
    for fpath in files_to_patch:
        if not fpath.exists():
            results.append(
                {"file": str(fpath), "action": "error", "reason": "file not found"}
            )
            continue
        try:
            result = patch_file(fpath)
            results.append(result)
        except Exception as e:
            results.append({"file": str(fpath), "action": "error", "reason": str(e)})

    print(f"\n{'='*60}")
    print("PROVENANCE PATCH 2 — добивка без frontmatter")
    print(f"{'='*60}")
    for r in results:
        icon = (
            "✅"
            if r["action"] in ("added_frontmatter",)
            else "⏭"
            if r["action"] == "skip"
            else "❌"
        )
        print(
            f"  {icon} {r['file']}: {r['action']}  {r.get('reason', '')}  source={r.get('source', '')}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
