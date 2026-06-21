#!/usr/bin/env python3
"""
artifact_link_checker.py — проверка целостности ссылок между артефактами LabDoctorM.

Находит:
- Разорванные ссылки (ссылка на несуществующий артефакт)
- Орфанные артефакты (без inbound links)
- Взаимные ссылки (A→B но нет B→A)
- Ссылки на архивные/устаревшие артефакты

Usage:
  python3 artifact_link_checker.py [--fix] [--json] [--report]
"""

import sys
import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import parse_frontmatter, load_all_artifacts as _canonical_load_all

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()

# Match artifact IDs: PAT-001, ADR-012, RUL-005, BL-028, INC-003, MET-001
ID_PATTERN = re.compile(r"\b([A-Z]{2,4}-\d{3,4})\b")
# Match markdown links: [text](path)
MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# Match wiki-style links: [[ART-001]]
WIKI_LINK_PATTERN = re.compile(r"\[\[([A-Z]{2,4}-\d{3,4})\]\]")

TEMPLATE_NAMES = {"template", "шаблон", "readme"}


def load_all_artifacts() -> dict[str, dict]:
    """Load all artifacts into memory. Returns {id: {path, meta, body, ...}}"""
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def extract_links(content: str) -> set[str]:
    """Extract all artifact ID references from content."""
    links = set()

    # Direct ID references (PAT-001, ADR-012, etc.)
    for m in ID_PATTERN.finditer(content):
        links.add(m.group(1))

    # Markdown links that contain artifact IDs
    for text, href in MD_LINK_PATTERN.findall(content):
        for m in ID_PATTERN.finditer(text + " " + href):
            links.add(m.group(1))

    # Wiki-style links
    for m in WIKI_LINK_PATTERN.finditer(content):
        links.add(m.group(1))

    return links


def check_links(artifacts: dict) -> dict:
    """Run all link checks. Returns detailed report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # Build link graph
    outbound = defaultdict(set)  # aid -> set of referenced aids
    inbound = defaultdict(set)   # aid -> set of aids referencing it

    all_ids = set(artifacts.keys())

    for aid, art in artifacts.items():
        links = extract_links(art["full_content"])
        # Remove self-references
        links.discard(aid)
        # Only keep links to known artifacts
        valid_links = links & all_ids
        outbound[aid] = valid_links
        for target in valid_links:
            inbound[target].add(aid)

    # Find broken links (reference to non-existent artifact)
    broken_links = []
    for aid, art in artifacts.items():
        links = extract_links(art["full_content"])
        links.discard(aid)
        broken = links - all_ids
        for b in broken:
            # Check if it looks like a valid artifact ID (not just random uppercase)
            if re.match(r"^[A-Z]{2,4}-\d{3,4}$", b):
                broken_links.append({
                    "from": aid,
                    "to": b,
                    "from_file": art["file"],
                    "from_status": art["status"],
                })

    # Find orphans (no inbound links)
    orphans = []
    for aid, art in artifacts.items():
        if art["status"] in ("archived", "rejected"):
            continue
        if aid == "INS-001":
            continue  # Special case
        if not inbound.get(aid):
            orphans.append({
                "id": aid,
                "type": art["type"],
                "title": art["title"],
                "file": art["file"],
                "status": art["status"],
                "outbound_count": len(outbound.get(aid, set())),
            })

    # Find links to archived/stale artifacts
    deprecated_links = []
    for aid, art in artifacts.items():
        if art["status"] in ("active", "accepted", "unknown"):
            continue
        for referrer in inbound.get(aid, set()):
            deprecated_links.append({
                "from": referrer,
                "to": aid,
                "target_status": art["status"],
                "target_title": art["title"],
            })

    # Find missing reciprocal links (A→B but B→A doesn't exist)
    missing_reciprocal = []
    for aid, targets in outbound.items():
        for target in targets:
            if aid not in outbound.get(target, set()):
                # Only report once (aid < target to avoid duplicates)
                if aid < target:
                    missing_reciprocal.append({
                        "from": aid,
                        "to": target,
                        "direction": "one-way",
                    })

    # Stats
    total_links = sum(len(t) for t in outbound.values())
    total_artifacts = len(artifacts)
    linked_artifacts = len(set(outbound.keys()) | set(inbound.keys()))

    return {
        "timestamp": now,
        "total_artifacts": total_artifacts,
        "linked_artifacts": linked_artifacts,
        "isolation_rate": round((total_artifacts - linked_artifacts) / max(total_artifacts, 1) * 100, 1),
        "total_links": total_links,
        "broken_links": {
            "count": len(broken_links),
            "items": broken_links,
        },
        "orphans": {
            "count": len(orphans),
            "items": orphans,
        },
        "deprecated_links": {
            "count": len(deprecated_links),
            "items": deprecated_links,
        },
        "missing_reciprocal": {
            "count": len(missing_reciprocal),
            "items": missing_reciprocal[:50],  # Cap for readability
        },
        "most_referenced": sorted(
            [(aid, len(refs)) for aid, refs in inbound.items()],
            key=lambda x: x[1], reverse=True
        )[:10],
        "most_referencing": sorted(
            [(aid, len(targets)) for aid, targets in outbound.items()],
            key=lambda x: x[1], reverse=True
        )[:10],
    }


def format_report(report: dict) -> str:
    """Format report as human-readable text."""
    lines = [
        "═══ ARTIFACT LINK CHECKER REPORT ═══",
        f"Generated: {report['timestamp']}",
        f"",
        f"Artifacts: {report['total_artifacts']} total, {report['linked_artifacts']} linked",
        f"Isolation rate: {report['isolation_rate']}%",
        f"Total links: {report['total_links']}",
        f"",
    ]

    # Broken links
    bl = report["broken_links"]
    lines.append(f"── Broken Links: {bl['count']} ──")
    if bl["count"] == 0:
        lines.append("  ✅ None")
    for item in bl["items"]:
        lines.append(f"  ❌ {item['from']} → {item['to']} (in {item['from_file']}, status: {item['from_status']})")
    lines.append("")

    # Orphans
    op = report["orphans"]
    lines.append(f"── Orphans (no inbound links): {op['count']} ──")
    if op["count"] == 0:
        lines.append("  ✅ None")
    for item in op["items"]:
        lines.append(f"  ⚠️  {item['id']} ({item['type']}) — {item['title']}")
        lines.append(f"       file: {item['file']} | outbound: {item['outbound_count']}")
    lines.append("")

    # Deprecated links
    dl = report["deprecated_links"]
    lines.append(f"── Links to Archived/Deprecated: {dl['count']} ──")
    if dl["count"] == 0:
        lines.append("  ✅ None")
    for item in dl["items"][:20]:
        lines.append(f"  ⚠️  {item['from']} → {item['to']} ({item['target_status']}: {item['target_title']})")
    if dl["count"] > 20:
        lines.append(f"  ... and {dl['count'] - 20} more")
    lines.append("")

    # Missing reciprocal
    mr = report["missing_reciprocal"]
    lines.append(f"── One-way Links (missing reciprocal): {mr['count']} ──")
    if mr["count"] == 0:
        lines.append("  ✅ All links are bidirectional")
    for item in mr["items"][:10]:
        lines.append(f"  → {item['from']} → {item['to']} (no {item['to']} → {item['from']})")
    if mr["count"] > 10:
        lines.append(f"  ... and {mr['count'] - 10} more")
    lines.append("")

    # Most referenced
    lines.append("── Most Referenced Artifacts ──")
    for aid, count in report["most_referenced"]:
        lines.append(f"  🔗 {aid}: {count} inbound links")
    lines.append("")

    # Most referencing
    lines.append("── Most Referencing Artifacts ──")
    for aid, count in report["most_referencing"]:
        lines.append(f"  📤 {aid}: {count} outbound links")
    lines.append("")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Check artifact link integrity")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--report", action="store_true", help="Save report to file")
    parser.add_argument("--fix", action="store_true", help="Interactive fix suggestions")
    args = parser.parse_args()

    artifacts = load_all_artifacts()
    report = check_links(artifacts)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        text_report = format_report(report)
        print(text_report)

        if args.report:
            report_path = LAB_DIR / ".qwen/artifacts/link_check_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"Report saved: {report_path}")

    # Exit code: 0 if no issues, 1 if issues found
    issues = report["broken_links"]["count"] + report["orphans"]["count"]
    sys.exit(1 if issues > 0 else 0)


if __name__ == "__main__":
    main()
