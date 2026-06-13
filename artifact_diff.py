#!/usr/bin/env python3
"""
artifact_diff.py — сравнение двух артефактов LabDoctorM.

Показывает различия:
- Изменения в frontmatter-полях
- Изменения в исходящих ссылках (добавленные/удалённые)
- Изменения во входящих ссылках
- Изменение health score

Usage:
  python3 artifact-diff.py ARTIFACT_ID_1 ARTIFACT_ID_2 [--json]
"""

import sys
import json
import argparse
from pathlib import Path
from difflib import unified_diff
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import load_all_artifacts as _canonical_load_all
from artifact_constants import REF_PATTERN
from artifact_health import check_frontmatter, check_links, check_aging, check_code_refs, compute_overall_score
from typing import Any

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()


def load_all_artifacts() -> dict:
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def _get_outbound_refs(body: str) -> set[str]:
    """Extract all outbound references from body."""
    return set(REF_PATTERN.findall(body))


def _get_inbound_refs(artifacts: dict, target_id: str) -> set[str]:
    """Find all artifacts that reference target_id."""
    sources = set()
    for aid, art in artifacts.items():
        if aid == target_id:
            continue
        body = art.body if hasattr(art, "body") else art.get("body", art.get("_body", ""))
        refs = _get_outbound_refs(body)
        if target_id in refs:
            sources.add(aid)
    return sources


def _compute_artifacts_health(artifacts: dict) -> dict:
    """Compute per-dimension health scores for all artifacts."""
    checks = {
        "frontmatter": check_frontmatter(artifacts),
        "links": check_links(artifacts),
        "aging": check_aging(artifacts),
        "code_refs": check_code_refs(artifacts),
    }
    overall = compute_overall_score(checks)
    return overall


def _format_val(val: Any) -> str:
    """Format a value for display."""
    if val is None:
        return "(none)"
    if isinstance(val, list):
        return ", ".join(str(v) for v in val) if val else "(empty)"
    return str(val)


def compute_diff(artifacts: dict, id1: str, id2: str) -> dict:
    """Compute full diff between two artifacts."""
    art1 = artifacts[id1]
    art2 = artifacts[id2]

    # Frontmatter field differences
    meta1 = art1["meta"]
    meta2 = art2["meta"]

    all_fields = sorted(set(meta1.keys()) | set(meta2.keys()))
    field_changes = []
    for field in all_fields:
        v1 = meta1.get(field)
        v2 = meta2.get(field)
        if v1 != v2:
            field_changes.append({
                "field": field,
                "old": v1,
                "new": v2,
            })

    # Body diff
    body1_lines = art1["body"].splitlines(keepends=True)
    body2_lines = art2["body"].splitlines(keepends=True)
    body_diff = list(unified_diff(
        body1_lines, body2_lines,
        fromfile=f"{id1}/body", tofile=f"{id2}/body",
        lineterm="",
    ))

    # Outbound reference differences
    refs1_out = _get_outbound_refs(art1["body"])
    refs2_out = _get_outbound_refs(art2["body"])
    added_refs = sorted(refs2_out - refs1_out)
    removed_refs = sorted(refs1_out - refs2_out)

    # Inbound reference differences
    inbound1 = _get_inbound_refs(artifacts, id1)
    inbound2 = _get_inbound_refs(artifacts, id2)
    added_inbound = sorted(inbound2 - inbound1)
    removed_inbound = sorted(inbound1 - inbound2)

    return {
        "artifact_1": id1,
        "artifact_2": id2,
        "title_1": art1["title"],
        "title_2": art2["title"],
        "type_1": art1["type"],
        "type_2": art2["type"],
        "status_1": art1["status"],
        "status_2": art2["status"],
        "field_changes": field_changes,
        "body_diff": body_diff,
        "outbound_refs": {
            "added": added_refs,
            "removed": removed_refs,
            "common": sorted(refs1_out & refs2_out),
        },
        "inbound_refs": {
            "added": added_inbound,
            "removed": removed_inbound,
            "common": sorted(inbound1 & inbound2),
        },
    }


def format_diff_text(diff: dict) -> str:
    """Format diff as human-readable text."""
    lines = []

    id1 = diff["artifact_1"]
    id2 = diff["artifact_2"]

    lines.append(f"═══ DIFF: {id1} → {id2} ═══")
    lines.append(f"  {id1}: [{diff['type_1']}] {diff['title_1']} (status: {diff['status_1']})")
    lines.append(f"  {id2}: [{diff['type_2']}] {diff['title_2']} (status: {diff['status_2']})")
    lines.append("")

    # Field changes
    lines.append("── Field Changes ──")
    if diff["field_changes"]:
        for fc in diff["field_changes"]:
            lines.append(f"  {fc['field']:<16} {_format_val(fc['old']):<25} → {_format_val(fc['new'])}")
    else:
        lines.append("  (no changes)")
    lines.append("")

    # Outbound refs
    or_ = diff["outbound_refs"]
    lines.append("── Outbound References ──")
    if or_["added"]:
        for r in or_["added"]:
            lines.append(f"  + {r}")
    if or_["removed"]:
        for r in or_["removed"]:
            lines.append(f"  - {r}")
    if or_["common"]:
        for r in or_["common"]:
            lines.append(f"  = {r}")
    if not or_["added"] and not or_["removed"]:
        lines.append("  (no changes)")
    lines.append("")

    # Inbound refs
    ir = diff["inbound_refs"]
    lines.append("── Inbound References ──")
    if ir["added"]:
        for r in ir["added"]:
            lines.append(f"  + {r}")
    if ir["removed"]:
        for r in ir["removed"]:
            lines.append(f"  - {r}")
    if ir["common"]:
        for r in ir["common"]:
            lines.append(f"  = {r}")
    if not ir["added"] and not ir["removed"]:
        lines.append("  (no changes)")
    lines.append("")

    # Body diff
    lines.append("── Body Diff ──")
    if diff["body_diff"]:
        for line in diff["body_diff"][:50]:
            lines.append(f"  {line}")
        if len(diff["body_diff"]) > 50:
            lines.append(f"  ... {len(diff['body_diff']) - 50} more lines ...")
    else:
        lines.append("  (no changes)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare two artifacts")
    parser.add_argument("artifact_1", help="First artifact ID")
    parser.add_argument("artifact_2", help="Second artifact ID")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    artifacts = load_all_artifacts()

    if args.artifact_1 not in artifacts:
        print(f"ERROR: Artifact {args.artifact_1} not found", file=sys.stderr)
        sys.exit(1)
    if args.artifact_2 not in artifacts:
        print(f"ERROR: Artifact {args.artifact_2} not found", file=sys.stderr)
        sys.exit(1)
    if args.artifact_1 == args.artifact_2:
        print("ERROR: Cannot diff an artifact with itself", file=sys.stderr)
        sys.exit(1)

    diff = compute_diff(artifacts, args.artifact_1, args.artifact_2)

    if args.json:
        # Make body_diff JSON-serializable
        output = {**diff, "body_diff": diff["body_diff"]}
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_diff_text(diff))


if __name__ == "__main__":
    main()
