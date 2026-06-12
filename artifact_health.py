#!/usr/bin/env python3
"""
artifact_health.py — проверка здоровья системы артефактов LabDoctorM.

Комплексный health check:
- Валидность frontmatter
- Целостность ссылок
- Старение артефактов
- Дубликаты
- Покрытие код-референсами
- Insights queue статус
- Общая оценка здоровья (0-100)

Usage:
  python3 artifact_health.py [--json] [--verbose] [--fix] [--output FILE]
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from config_loader import get_lab_dir, get_artifact_dirs, get_state_file
from artifact_core import load_all_artifacts as _canonical_load_all
from artifact_constants import (
    ID_PATTERN,
    REF_PATTERN,
    ALL_VALID_STATUSES,
    REQUIRED_FIELDS,
)

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()
QUEUE_FILE = get_state_file("insights_queue") or LAB_DIR / ".qwen/artifacts/insights_queue.json"
SEARCH_INDEX_FILE = get_state_file("search_index") or LAB_DIR / ".qwen/artifacts/search_index.json"
STATS_FILE = get_state_file("artifact_stats") or LAB_DIR / ".qwen/artifacts/artifact_stats.json"
CHANGELOG_FILE = get_state_file("changelog") or LAB_DIR / "ARTIFACT_CHANGELOG.md"


def load_all_artifacts() -> dict:
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def check_frontmatter(artifacts: dict) -> dict:
    """Validate frontmatter for all artifacts."""
    errors = []
    warnings = []
    total = len(artifacts)

    for aid, art in artifacts.items():
        meta = art["meta"]
        atype = art["type"]

        # Required fields
        required = REQUIRED_FIELDS.get(atype, ["id", "type", "title", "status"])
        for field in required:
            if field not in meta or not meta[field]:
                errors.append(f"{aid}: missing required field '{field}'")

        # Valid status
        if art["status"] not in ALL_VALID_STATUSES:
            warnings.append(f"{aid}: unknown status '{art['status']}'")

        # ID format
        if not ID_PATTERN.match(aid):
            warnings.append(f"{aid}: ID doesn't match expected format (XXX-NNN)")

        # Created date format
        if art["created"]:
            try:
                import datetime as _dt
                if isinstance(art["created"], (_dt.datetime, _dt.date)):
                    pass  # YAML already parsed it (datetime or date)
                elif isinstance(art["created"], str):
                    datetime.fromisoformat(art["created"].replace("+00:00", "+00:00"))
                else:
                    errors.append(f"{aid}: unexpected created type {type(art['created']).__name__}")
            except (ValueError, TypeError):
                errors.append(f"{aid}: invalid created date '{art['created']}'")

        # Title quality
        title = art["title"]
        if len(title) < 5:
            warnings.append(f"{aid}: title too short ({len(title)} chars)")
        if title == "?" or title == art["file"].split("/")[-1].replace(".md", ""):
            warnings.append(f"{aid}: untitled (title = filename)")

    return {
        "total": total,
        "errors": len(errors),
        "warnings": len(warnings),
        "error_details": errors[:20],
        "warning_details": warnings[:20],
        "score": max(0, 100 - len(errors) * 5 - len(warnings) * 1),
    }


def check_links(artifacts: dict) -> dict:
    """Check link integrity."""
    all_ids = set(artifacts.keys())
    outbound = defaultdict(set)
    inbound = defaultdict(set)

    broken = []
    orphans = []

    for aid, art in artifacts.items():
        links = set()
        for m in REF_PATTERN.finditer(art["full_content"]):
            links.add(m.group(1))
        links.discard(aid)
        valid = links & all_ids
        outbound[aid] = valid
        for t in valid:
            inbound[t].add(aid)

        broken_refs = links - all_ids
        for b in broken_refs:
            if ID_PATTERN.match(b):
                broken.append({"from": aid, "to": b})

    for aid, art in artifacts.items():
        if art["status"] in ("archived", "rejected"):
            continue
        if not inbound.get(aid) and not outbound.get(aid):
            orphans.append(aid)
        elif not inbound.get(aid):
            orphans.append(aid)

    total_links = sum(len(t) for t in outbound.values())
    active_count = sum(1 for a in artifacts.values() if a["status"] not in ("archived", "rejected"))

    return {
        "total_links": total_links,
        "broken_count": len(broken),
        "orphan_count": len(orphans),
        "broken_details": broken[:10],
        "orphan_details": orphans[:10],
        "linked_ratio": round((active_count - len(orphans)) / max(active_count, 1) * 100, 1),
        "score": max(0, 100 - len(broken) * 10 - len(orphans) * 3),
    }


def check_aging(artifacts: dict) -> dict:
    """Check for stale artifacts."""
    now = datetime.now(timezone.utc)
    stale_days = 90
    archive_days = 180

    stale = []
    needs_archive = []

    for aid, art in artifacts.items():
        if art["status"] in ("archived", "rejected"):
            continue

        updated = art.get("updated") or art.get("created")
        if not updated:
            continue

        try:
            import datetime as _dt
            if isinstance(updated, _dt.datetime):
                updated_dt = updated
            elif isinstance(updated, _dt.date):
                updated_dt = datetime.combine(updated, datetime.min.time(), tzinfo=timezone.utc)
            elif isinstance(updated, str):
                updated_dt = datetime.fromisoformat(updated.replace("+00:00", "+00:00"))
            else:
                continue
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            age_days = (now - updated_dt).days
        except (ValueError, TypeError):
            continue

        if age_days > archive_days and art["status"] != "archived":
            needs_archive.append({"id": aid, "age_days": age_days, "status": art["status"]})
        elif age_days > stale_days:
            stale.append({"id": aid, "age_days": age_days, "status": art["status"]})

    return {
        "stale_count": len(stale),
        "needs_archive_count": len(needs_archive),
        "stale_details": stale[:10],
        "needs_archive_details": needs_archive[:10],
        "score": max(0, 100 - len(stale) * 2 - len(needs_archive) * 5),
    }


def check_duplicates(artifacts: dict) -> dict:
    """Check for potential duplicates."""
    title_map = defaultdict(list)
    for aid, art in artifacts.items():
        title_lower = art["title"].lower().strip()
        title_map[title_lower].append(aid)

    exact_dups = [ids for ids in title_map.values() if len(ids) > 1]

    # Check for near-duplicates (same keywords)
    keyword_map = defaultdict(list)
    for aid, art in artifacts.items():
        keywords = frozenset(w for w in art["title"].lower().split() if len(w) > 3)
        if keywords:
            keyword_map[keywords].append(aid)

    near_dups = [ids for ids in keyword_map.values() if len(ids) > 1]

    return {
        "exact_duplicates": len(exact_dups),
        "near_duplicates": len(near_dups),
        "exact_details": exact_dups[:5],
        "near_details": near_dups[:5],
        "score": max(0, 100 - len(exact_dups) * 20 - len(near_dups) * 5),
    }


def check_code_refs(artifacts: dict) -> dict:
    """Check code_refs coverage."""
    total_active = 0
    with_refs = 0
    empty_refs = 0

    for aid, art in artifacts.items():
        if art["status"] in ("archived", "rejected"):
            continue
        total_active += 1
        refs = art["meta"].get("code_refs", [])
        if refs:
            with_refs += 1
        else:
            empty_refs += 1

    coverage = round(with_refs / max(total_active, 1) * 100, 1)

    return {
        "total_active": total_active,
        "with_refs": with_refs,
        "empty_refs": empty_refs,
        "coverage_pct": coverage,
        "score": min(100, coverage * 2),  # 50% coverage = 100 score
    }


def check_insights_queue() -> dict:
    """Check insights queue status."""
    if not QUEUE_FILE.exists():
        return {"exists": False, "total": 0, "score": 50}

    try:
        data = json.loads(QUEUE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"exists": True, "total": 0, "error": True, "score": 0}

    insights = data.get("insights", [])
    total = len(insights)
    by_status = defaultdict(int)
    for i in insights:
        by_status[i.get("status", "unknown")] += 1

    promotable = sum(1 for i in insights if i.get("confirmations", 0) >= 2 and i.get("status") == "consolidated")

    return {
        "exists": True,
        "total": total,
        "by_status": dict(by_status),
        "promotable": promotable,
        "score": 100 if total > 0 else 50,
    }


def check_infrastructure() -> dict:
    """Check supporting infrastructure."""
    checks = {}

    # Search index
    checks["search_index"] = {
        "exists": SEARCH_INDEX_FILE.exists(),
        "size_kb": round(SEARCH_INDEX_FILE.stat().st_size / 1024) if SEARCH_INDEX_FILE.exists() else 0,
    }

    # Stats file
    checks["stats_file"] = {
        "exists": STATS_FILE.exists(),
    }

    # Changelog
    checks["changelog"] = {
        "exists": CHANGELOG_FILE.exists(),
    }

    # Scripts —оригиналы в .qwen/scripts, проект-копии в projects/artifact-pulse/
    scripts_dir = LAB_DIR / ".qwen/scripts"
    pulse_src = LAB_DIR / "projects/artifact-pulse/src"
    pulse_scripts = LAB_DIR / "projects/artifact-pulse/scripts"
    expected_scripts = [
        "artifact_aging.py",
        "artifact_stats.py",
        "artifact_link_checker.py",
        "artifact_graph.py",
        "artifact_health.py",
        "artifact_changelog.py",
        "search_artifacts.py",
    ]
    expected_shell = [
        "evolve_orchestrator.sh",
        "self_evolve.sh",
    ]
    missing = []
    for s in expected_scripts:
        if not (scripts_dir / s).exists() and not (pulse_src / s).exists():
            missing.append(s)
    for s in expected_shell:
        if not (scripts_dir / s).exists() and not (pulse_scripts / s).exists():
            missing.append(s)
    total_expected = len(expected_scripts) + len(expected_shell)
    checks["scripts"] = {
        "expected": total_expected,
        "found": total_expected - len(missing),
        "missing": missing,
    }

    score = 100
    if not checks["search_index"]["exists"]:
        score -= 10
    if not checks["stats_file"]["exists"]:
        score -= 5
    if missing:
        score -= len(missing) * 5

    checks["score"] = max(0, score)
    return checks


def check_provenance_dimension(artifacts: dict) -> dict:
    """Check provenance coverage (last_verified, confidence, source)."""
    total_active = 0
    has_verified = 0
    has_confidence = 0
    has_source = 0
    outdated = 0
    from datetime import datetime, timezone

    for aid, art in artifacts.items():
        if art["status"] in ("archived", "rejected"):
            continue
        total_active += 1

        if art.get("last_verified"):
            has_verified += 1
            try:
                v = art["last_verified"]
                import datetime as _dt
                if isinstance(v, _dt.datetime):
                    v_dt = v
                elif isinstance(v, _dt.date):
                    v_dt = datetime.combine(v, datetime.min.time(), tzinfo=timezone.utc)
                elif isinstance(v, str):
                    v_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                else:
                    outdated += 1
                    continue
                if v_dt.tzinfo is None:
                    v_dt = v_dt.replace(tzinfo=timezone.utc)
                days = (datetime.now(timezone.utc) - v_dt).days
                if days > 90:
                    outdated += 1
            except (ValueError, TypeError):
                outdated += 1

        if art.get("confidence") and art["confidence"] not in ("unknown",):
            has_confidence += 1

        if art.get("source") and art["source"] not in ("unknown",):
            has_source += 1

    if total_active == 0:
        return {"score": 100, "total_active": 0}

    verified_pct = has_verified / total_active * 100
    confidence_pct = has_confidence / total_active * 100
    source_pct = has_source / total_active * 100
    outdated_pct = outdated / total_active * 100

    score = (
        verified_pct * 0.4 +
        confidence_pct * 0.2 +
        source_pct * 0.2 +
        (100 - outdated_pct) * 0.2
    )

    return {
        "total_active": total_active,
        "verified_pct": round(verified_pct, 1),
        "confidence_pct": round(confidence_pct, 1),
        "source_pct": round(source_pct, 1),
        "outdated_count": outdated,
        "score": round(score),
    }


def check_constraints_dimension(artifacts: dict) -> dict:
    """Check constraint violations."""
    from artifact_constraints import build_link_graph, check_structural_constraints

    outbound, inbound = build_link_graph(artifacts)
    violations = check_structural_constraints(artifacts, outbound, inbound)

    errors = sum(1 for v in violations if v["severity"] == "error")
    warnings = sum(1 for v in violations if v["severity"] == "warning")
    score = max(0, 100 - errors * 15 - warnings * 2)

    return {
        "violations": len(violations),
        "errors": errors,
        "warnings": warnings,
        "score": score,
    }


def compute_overall_score(checks: dict) -> int:
    """Compute weighted overall health score."""
    weights = {
        "frontmatter": 0.20,
        "links": 0.20,
        "aging": 0.10,
        "duplicates": 0.10,
        "code_refs": 0.10,
        "provenance": 0.10,
        "constraints": 0.10,
        "insights": 0.05,
        "infrastructure": 0.05,
    }

    total = 0
    for key, weight in weights.items():
        if key in checks and "score" in checks[key]:
            total += checks[key]["score"] * weight

    return round(total)


def format_report(checks: dict, overall: int) -> str:
    """Format health check as human-readable report."""
    status_emoji = "🟢" if overall >= 80 else "🟡" if overall >= 60 else "🔴"

    lines = [
        "═══ ARTIFACT SYSTEM HEALTH CHECK ═══",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"{status_emoji} Overall Health Score: {overall}/100",
        "",
    ]

    # Frontmatter
    fm = checks["frontmatter"]
    emoji = "✅" if fm["errors"] == 0 else "❌"
    lines.append(f"── Frontmatter {emoji} ({fm['score']}/100) ──")
    lines.append(f"  Total: {fm['total']} | Errors: {fm['errors']} | Warnings: {fm['warnings']}")
    for e in fm["error_details"][:5]:
        lines.append(f"  ❌ {e}")
    for w in fm["warning_details"][:3]:
        lines.append(f"  ⚠️  {w}")
    lines.append("")

    # Links
    lk = checks["links"]
    emoji = "✅" if lk["broken_count"] == 0 and lk["orphan_count"] == 0 else "⚠️"
    lines.append(f"── Links {emoji} ({lk['score']}/100) ──")
    lines.append(f"  Total links: {lk['total_links']} | Broken: {lk['broken_count']} | Orphans: {lk['orphan_count']}")
    lines.append(f"  Linked ratio: {lk['linked_ratio']}%")
    for b in lk["broken_details"][:5]:
        lines.append(f"  ❌ {b['from']} → {b['to']}")
    lines.append("")

    # Aging
    ag = checks["aging"]
    emoji = "✅" if ag["stale_count"] == 0 and ag["needs_archive_count"] == 0 else "⚠️"
    lines.append(f"── Aging {emoji} ({ag['score']}/100) ──")
    lines.append(f"  Stale (>90d): {ag['stale_count']} | Needs archive (>180d): {ag['needs_archive_count']}")
    for s in ag["stale_details"][:3]:
        lines.append(f"  ⚠️  {s['id']}: {s['age_days']} days old")
    lines.append("")

    # Duplicates
    dup = checks["duplicates"]
    emoji = "✅" if dup["exact_duplicates"] == 0 else "❌"
    lines.append(f"── Duplicates {emoji} ({dup['score']}/100) ──")
    lines.append(f"  Exact: {dup['exact_duplicates']} | Near: {dup['near_duplicates']}")
    for d in dup["exact_details"][:3]:
        lines.append(f"  ❌ {', '.join(d)}")
    lines.append("")

    # Code refs
    cr = checks["code_refs"]
    emoji = "✅" if cr["coverage_pct"] >= 50 else "⚠️"
    lines.append(f"── Code Refs {emoji} ({cr['score']}/100) ──")
    lines.append(f"  Coverage: {cr['coverage_pct']}% ({cr['with_refs']}/{cr['total_active']})")
    lines.append("")

    # Provenance
    if "provenance" in checks:
        pr = checks["provenance"]
        emoji = "✅" if pr["score"] >= 80 else "⚠️"
        lines.append(f"── Provenance {emoji} ({pr['score']}/100) ──")
        lines.append(f"  Verified: {pr.get('verified_pct', 0)}% | Source: {pr.get('source_pct', 0)}% | Outdated: {pr.get('outdated_count', 0)}")
        lines.append("")

    # Constraints
    if "constraints" in checks:
        cn = checks["constraints"]
        emoji = "✅" if cn["score"] >= 80 else "⚠️"
        lines.append(f"── Constraints {emoji} ({cn['score']}/100) ──")
        lines.append(f"  Violations: {cn['violations']} | Errors: {cn['errors']} | Warnings: {cn['warnings']}")
        lines.append("")

    # Insights
    iq = checks["insights"]
    lines.append(f"── Insights Queue ({iq['score']}/100) ──")
    if iq["exists"]:
        lines.append(f"  Total: {iq['total']} | Promotable: {iq.get('promotable', 0)}")
        for status, count in iq.get("by_status", {}).items():
            lines.append(f"  {status}: {count}")
    else:
        lines.append("  Queue file not found")
    lines.append("")

    # Infrastructure
    inf = checks["infrastructure"]
    emoji = "✅" if inf['score'] == 100 else "⚠️"
    lines.append(f"── Infrastructure {emoji} ({inf['score']}/100) ──")
    lines.append(f"  Search index: {'✅' if inf['search_index']['exists'] else '❌'} ({inf['search_index'].get('size_kb', 0)} KB)")
    lines.append(f"  Stats file: {'✅' if inf['stats_file']['exists'] else '❌'}")
    lines.append(f"  Changelog: {'✅' if inf['changelog']['exists'] else '❌'}")
    lines.append(f"  Scripts: {inf['scripts']['found']}/{inf['scripts']['expected']}")
    if inf["scripts"]["missing"]:
        for m in inf["scripts"]["missing"]:
            lines.append(f"    ❌ Missing: {m}")
    lines.append("")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Artifact system health check")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--output", type=str, help="Output file path")
    args = parser.parse_args()

    artifacts = load_all_artifacts()

    checks = {
        "frontmatter": check_frontmatter(artifacts),
        "links": check_links(artifacts),
        "aging": check_aging(artifacts),
        "duplicates": check_duplicates(artifacts),
        "code_refs": check_code_refs(artifacts),
        "provenance": check_provenance_dimension(artifacts),
        "constraints": check_constraints_dimension(artifacts),
        "insights": check_insights_queue(),
        "infrastructure": check_infrastructure(),
    }

    overall = compute_overall_score(checks)

    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "overall_score": overall,
        "checks": checks,
    }

    if args.json:
        output = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        output = format_report(checks, overall)

    if args.output:
        Path(args.output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) if args.json else output,
            encoding="utf-8",
        )
        print(f"Report saved: {args.output}")
    else:
        print(output)

    # Exit code based on health
    if overall >= 80:
        sys.exit(0)
    elif overall >= 60:
        sys.exit(0)  # Warning but not failure
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
