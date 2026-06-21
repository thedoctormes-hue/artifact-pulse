#!/usr/bin/env python3
"""
artifact_constraints.py — валидация ограничений и обнаружение противоречий в артефактах.

Проверяет структурные правила (constraints) и семантические противоречия:
- Каждый ADR должен ссылаться хотя бы на один другой артефакт
- Каждый incident должен иметь severity
- Каждый spec должен иметь секцию "Интерфейс" или "API"
- Архивированные артефакты не должны быть целью ссылок из активных
- Обнаружение пар артефактов с одинаковым заголовком (потенциальные дубликаты)
- Обнаружение циклических зависимостей (A→B→C→A)
- Обнаружение противоречий в статусах (active incident > 180d)

Usage:
  python3 artifact_constraints.py [--json] [--fix] [--verbose]
"""

import sys
import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import parse_frontmatter, load_all_artifacts as _canonical_load_all

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()

TEMPLATE_NAMES = {"template", "шаблон", "readme"}
ID_PATTERN = re.compile(r"\b([A-Z]{2,4}-\d{3,4})\b")
REF_PATTERN = re.compile(r"\b([A-Z]{2,4}-\d{3,4})\b")


def load_all_artifacts() -> dict:
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def build_link_graph(artifacts: dict) -> tuple[dict, dict]:
    """Build outbound and inbound link graphs."""
    outbound = defaultdict(set)
    inbound = defaultdict(set)
    all_ids = set(artifacts.keys())

    for aid, art in artifacts.items():
        refs = set(REF_PATTERN.findall(art["full_content"]))
        refs.discard(aid)
        valid = refs & all_ids
        outbound[aid] = valid
        for t in valid:
            inbound[t].add(aid)

    return outbound, inbound


def find_cycles(outbound: dict) -> list:
    """Find circular dependencies in artifact link graph using DFS."""
    cycles = []
    visited = set()
    rec_stack = set()
    path = []

    def dfs(node):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in outbound.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                # Normalize: start from smallest element
                min_idx = cycle[:-1].index(min(cycle[:-1]))
                normalized = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                if normalized not in cycles:
                    cycles.append(normalized)

        path.pop()
        rec_stack.discard(node)

    for node in outbound:
        if node not in visited:
            dfs(node)

    return cycles


def check_structural_constraints(artifacts: dict, outbound: dict, inbound: dict) -> list:
    """Check structural constraint rules."""
    violations = []

    for aid, art in artifacts.items():
        atype = art["type"]
        status = art["status"]

        # Rule 1: ADR must reference at least one other artifact
        if atype == "adr" and status not in ("archived", "rejected"):
            if not outbound.get(aid) and not inbound.get(aid):
                violations.append({
                    "rule": "ADR-ISOLATED",
                    "severity": "warning",
                    "artifact": aid,
                    "message": f"{aid}: ADR has no links to/from other artifacts",
                })

        # Rule 1b: ADR/PAT must have code_refs (traceability to code)
        if atype in ("adr", "pattern") and status not in ("archived", "rejected", "draft"):
            has_code_refs = "code_refs" in art.get("meta", {}) and art["meta"]["code_refs"]
            if not has_code_refs:
                violations.append({
                    "rule": "MISSING-CODE-REFS",
                    "severity": "info",
                    "artifact": aid,
                    "message": f"{aid}: {atype} missing code_refs (no traceability to code)",
                })

        # Rule 2: Incident must have severity
        if atype == "incident" and status not in ("archived", "closed"):
            if not art.get("severity"):
                violations.append({
                    "rule": "INC-NO-SEVERITY",
                    "severity": "error",
                    "artifact": aid,
                    "message": f"{aid}: incident missing severity field",
                })

        # Rule 3: Spec must have API/Interface section
        if atype == "spec" and status not in ("archived", "rejected", "draft"):
            body_lower = art["body"].lower()
            if not any(h in body_lower for h in ["## интерфейс", "## api", "## interface", "## поведение"]):
                violations.append({
                    "rule": "SPEC-NO-INTERFACE",
                    "severity": "warning",
                    "artifact": aid,
                    "message": f"{aid}: spec missing Interface/API section",
                })

        # Rule 4: Active artifact referencing archived (not template)
        if status not in ("archived", "rejected"):
            for target in outbound.get(aid, set()):
                if target in artifacts and artifacts[target]["status"] == "archived":
                    violations.append({
                        "rule": "LINK-TO-ARCHIVED",
                        "severity": "info",
                        "artifact": aid,
                        "message": f"{aid} → {target}: active artifact links to archived",
                    })

    return violations


def check_temporal_contradictions(artifacts: dict) -> list:
    """Check for temporal contradictions (e.g., open incident too old)."""
    contradictions = []
    now = datetime.now(timezone.utc)

    for aid, art in artifacts.items():
        atype = art["type"]
        status = art["status"]

        # Open/resolved incident older than 180 days
        if atype == "incident" and status in ("open", "resolved"):
            ref_date = art.get("updated") or art.get("created")
            if ref_date:
                try:
                    dt = datetime.fromisoformat(str(ref_date).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (now - dt).days
                    if age > 180:
                        contradictions.append({
                            "rule": "STALE-INCIDENT",
                            "severity": "warning",
                            "artifact": aid,
                            "message": f"{aid}: incident status='{status}' but {age} days old — should be closed or archived",
                            "age_days": age,
                        })
                except (ValueError, TypeError):
                    pass

        # Proposed ADR older than 90 days
        if atype == "adr" and status == "proposed":
            ref_date = art.get("created")
            if ref_date:
                try:
                    dt = datetime.fromisoformat(str(ref_date).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (now - dt).days
                    if age > 90:
                        contradictions.append({
                            "rule": "STALE-PROPOSAL",
                            "severity": "warning",
                            "artifact": aid,
                            "message": f"{aid}: ADR proposed {age} days ago — needs decision",
                            "age_days": age,
                        })
                except (ValueError, TypeError):
                    pass

    return contradictions


def check_naming_conflicts(artifacts: dict) -> list:
    """Check for potential naming conflicts and near-duplicates."""
    conflicts = []

    # Group by normalized title
    by_title = defaultdict(list)
    for aid, art in artifacts.items():
        normalized = art["title"].lower().strip()
        normalized = re.sub(r"[^a-z0-9а-яё]", "", normalized)
        if normalized:
            by_title[normalized].append(aid)

    for title, ids in by_title.items():
        if len(ids) > 1:
            # Check if they're different types (real conflict) or same type (duplicate)
            types = set(artifacts[i]["type"] for i in ids)
            severity = "warning" if len(types) > 1 else "error"
            conflicts.append({
                "rule": "TITLE-CONFLICT",
                "severity": severity,
                "artifact": ", ".join(ids),
                "message": f"Artifacts {', '.join(ids)} have identical title '{title}'",
            })

    return conflicts


def check_status_consistency(artifacts: dict, outbound: dict) -> list:
    """Check for status inconsistencies between linked artifacts."""
    issues = []

    for aid, art in artifacts.items():
        # If artifact references another with very different status
        for target in outbound.get(aid, set()):
            if target not in artifacts:
                continue
            target_art = artifacts[target]

            # Active artifact depends on deprecated one
            if art["status"] == "active" and target_art["status"] == "deprecated":
                issues.append({
                    "rule": "DEPENDS-ON-DEPRECATED",
                    "severity": "warning",
                    "artifact": aid,
                    "message": f"{aid} (active) depends on {target} (deprecated)",
                })

    return issues


def run_all_checks(artifacts: dict) -> dict:
    """Run all constraint and contradiction checks."""
    outbound, inbound = build_link_graph(artifacts)

    structural = check_structural_constraints(artifacts, outbound, inbound)
    temporal = check_temporal_contradictions(artifacts)
    naming = check_naming_conflicts(artifacts)
    status = check_status_consistency(artifacts, outbound)
    cycles = find_cycles(outbound)

    cycle_issues = []
    for cycle in cycles:
        cycle_issues.append({
            "rule": "CIRCULAR-DEP",
            "severity": "warning",
            "artifact": " → ".join(cycle),
            "message": f"Circular dependency: {' → '.join(cycle)}",
        })

    all_issues = structural + temporal + naming + status + cycle_issues

    errors = sum(1 for i in all_issues if i["severity"] == "error")
    warnings = sum(1 for i in all_issues if i["severity"] == "warning")
    infos = sum(1 for i in all_issues if i["severity"] == "info")

    score = max(0, 100 - errors * 10 - warnings * 1 - infos * 0.05)

    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "total_artifacts": len(artifacts),
        "total_issues": len(all_issues),
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "cycles_found": len(cycles),
        "score": score,
        "issues": all_issues,
        "summary_by_rule": _summarize_by_rule(all_issues),
    }


def _summarize_by_rule(issues: list) -> dict:
    summary = defaultdict(int)
    for i in issues:
        summary[i["rule"]] += 1
    return dict(sorted(summary.items(), key=lambda x: x[1], reverse=True))


def auto_fix(artifacts: dict, report: dict, dry_run: bool = True) -> dict:
    """Auto-fix simple constraint violations.

    Fixes applied:
    - INC-NO-SEVERITY: add severity=medium
    - STALE-INCIDENT: change status to closed
    - STALE-PROPOSAL: change status to accepted
    """
    from datetime import datetime, timezone
    fixes = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    for issue in report["issues"]:
        rule = issue["rule"]
        aid = issue["artifact"].split(" → ")[0].split(":")[0].strip()

        if aid not in artifacts:
            continue

        fpath = artifacts[aid].get("fpath")
        if not fpath:
            continue

        if rule == "INC-NO-SEVERITY":
            fix_desc = f"{aid}: add severity=medium"
            if not dry_run:
                try:
                    content = fpath.read_text(encoding="utf-8")
                    # Add severity after status line
                    lines = content.split("\n")
                    new_lines = []
                    added = False
                    for line in lines:
                        new_lines.append(line)
                        if not added and line.strip().startswith("status:"):
                            new_lines.append("severity: medium")
                            added = True
                    fpath.write_text("\n".join(new_lines), encoding="utf-8")
                    fixes.append({"rule": rule, "artifact": aid, "action": "added severity=medium"})
                except OSError as e:
                    fixes.append({"rule": rule, "artifact": aid, "action": f"FAILED: {e}"})
            else:
                fixes.append({"rule": rule, "artifact": aid, "action": "would add severity=medium (dry-run)"})

        elif rule == "STALE-INCIDENT":
            fix_desc = f"{aid}: close stale incident"
            if not dry_run:
                try:
                    content = fpath.read_text(encoding="utf-8")
                    new_content = content.replace("status: open", "status: closed")
                    new_content = new_content.replace("status: resolved", "status: closed")
                    new_content = new_content.replace("status: investigating", "status: closed")
                    # Update timestamp
                    new_content = new_content.replace(
                        f"updated: {artifacts[aid].get('meta', {}).get('updated', '')}",
                        f"updated: {now}"
                    )
                    fpath.write_text(new_content, encoding="utf-8")
                    fixes.append({"rule": rule, "artifact": aid, "action": "closed stale incident"})
                except OSError as e:
                    fixes.append({"rule": rule, "artifact": aid, "action": f"FAILED: {e}"})
            else:
                fixes.append({"rule": rule, "artifact": aid, "action": "would close stale incident (dry-run)"})

        elif rule == "STALE-PROPOSAL":
            if not dry_run:
                try:
                    content = fpath.read_text(encoding="utf-8")
                    new_content = content.replace("status: proposed", "status: accepted")
                    fpath.write_text(new_content, encoding="utf-8")
                    fixes.append({"rule": rule, "artifact": aid, "action": "accepted stale proposal"})
                except OSError as e:
                    fixes.append({"rule": rule, "artifact": aid, "action": f"FAILED: {e}"})
            else:
                fixes.append({"rule": rule, "artifact": aid, "action": "would accept stale proposal (dry-run)"})

    return {
        "dry_run": dry_run,
        "total_fixes": len(fixes),
        "fixes": fixes,
    }


def format_report(report: dict) -> str:
    lines = [
        "═══ ARTIFACT CONSTRAINTS & CONTRADICTIONS ═══",
        f"Generated: {report['timestamp']}",
        f"Artifacts: {report['total_artifacts']} | Issues: {report['total_issues']}",
        f"Errors: {report['errors']} | Warnings: {report['warnings']} | Info: {report['infos']}",
        f"Cycles: {report['cycles_found']} | Score: {report['score']}/100",
        "",
    ]

    if report["issues"]:
        # Group by severity
        for severity, emoji in [("error", "❌"), ("warning", "⚠️"), ("info", "ℹ️")]:
            items = [i for i in report["issues"] if i["severity"] == severity]
            if items:
                lines.append(f"── {emoji} {severity.upper()} ({len(items)}) ──")
                for item in items:
                    lines.append(f"  [{item['rule']}] {item['message']}")
                lines.append("")
    else:
        lines.append("✅ No constraint violations found!")
        lines.append("")

    if report["summary_by_rule"]:
        lines.append("── Summary by Rule ──")
        for rule, count in report["summary_by_rule"].items():
            lines.append(f"  {rule}: {count}")
        lines.append("")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Artifact constraint validation")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--fix", action="store_true", help="Auto-fix simple violations")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fixed without changing files")
    args = parser.parse_args()

    artifacts = load_all_artifacts()
    report = run_all_checks(artifacts)

    if args.fix or args.dry_run:
        fix_report = auto_fix(artifacts, report, dry_run=args.dry_run or not args.fix)
        if args.json:
            output = {"report": report, "fix": fix_report}
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(format_report(report))
            print(f"\n── Auto-Fix ({'dry-run' if args.dry_run or not args.fix else 'applied'}) ──")
            print(f"  Fixes: {fix_report['total_fixes']}")
            for f in fix_report["fixes"]:
                print(f"  [{f['rule']}] {f['artifact']}: {f['action']}")
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))

    if report["errors"] > 0:
        sys.exit(1)
    elif report["warnings"] > 5:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
