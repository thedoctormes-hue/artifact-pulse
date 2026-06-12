#!/usr/bin/env python3
"""
artifact_provenance.py — отслеживание происхождения и достоверности артефактов LabDoctorM.

Отслеживает:
- Источник артефакта (manual, agent, evolve_orchestrator, insight, import)
- Дата последней верификации (last_verified)
- Уровень достоверности (confidence: high/medium/low/outdated)
- Предстоящие ревью (review_due на основе типа и возраста)
- Старение достоверности (confidence decay)

Usage:
  python3 artifact_provenance.py [--verify ARTIFACT_ID] [--refresh] [--report] [--json]
"""

import sys
import re
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import (
    load_all_artifacts as _canonical_load_all,
)
from artifact_constants import (
    CONFIDENCE_DECAY,
    REVIEW_INTERVALS,
)

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()


def load_all_artifacts() -> dict:
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def compute_confidence(last_verified: str, current_confidence: str) -> str:
    """Compute effective confidence based on time since last verification."""
    if not last_verified:
        return "outdated"

    try:
        verified_dt = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
        if verified_dt.tzinfo is None:
            verified_dt = verified_dt.replace(tzinfo=timezone.utc)
        days_since = (datetime.now(timezone.utc) - verified_dt).days
    except (ValueError, TypeError):
        return "outdated"

    for threshold, confidence in CONFIDENCE_DECAY:
        if days_since <= threshold:
            return confidence
    return "outdated"


def compute_review_due(artifact: dict) -> str | None:
    """Compute next review due date based on type and last update."""
    atype = artifact.get("type", "spec")
    interval = REVIEW_INTERVALS.get(atype, 90)

    # Use last_verified if available, otherwise updated, otherwise created
    ref_date = artifact.get("last_verified") or artifact.get("updated") or artifact.get("created")
    if not ref_date:
        return None

    try:
        ref_dt = datetime.fromisoformat(str(ref_date).replace("Z", "+00:00"))
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        due_dt = ref_dt + timedelta(days=interval)
        return due_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def verify_artifact(artifact_id: str) -> dict:
    """Mark an artifact as verified today."""
    artifacts = load_all_artifacts()
    if artifact_id not in artifacts:
        return {"error": f"Artifact {artifact_id} not found"}

    art = artifacts[artifact_id]
    fpath = art["fpath"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    content = fpath.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    new_lines = []
    in_frontmatter = False
    had_last_verified = False
    had_confidence = False

    for i, line in enumerate(lines):
        if i == 0 and line.strip() == "---":
            in_frontmatter = True
            new_lines.append(line)
            continue
        if in_frontmatter and line.strip() == "---":
            in_frontmatter = False
            if not had_last_verified:
                new_lines.append(f"last_verified: {now}")
                had_last_verified = True
            if not had_confidence:
                new_lines.append("confidence: high")
                had_confidence = True
            new_lines.append(line)
            continue
        if in_frontmatter:
            if line.startswith("last_verified:"):
                new_lines.append(f"last_verified: {now}")
                had_last_verified = True
            elif line.startswith("confidence:"):
                new_lines.append("confidence: high")
                had_confidence = True
            elif line.startswith("updated:"):
                new_lines.append(line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    fpath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return {
        "id": artifact_id,
        "last_verified": now,
        "confidence": "high",
        "file": art["file"],
    }


def refresh_all_provenance() -> dict:
    """Refresh confidence for all artifacts based on decay rules."""
    artifacts = load_all_artifacts()
    refreshed = 0
    details = []

    for aid, art in artifacts.items():
        effective = compute_confidence(art.get("last_verified", ""), art.get("confidence", "medium"))
        if effective != art.get("confidence", "medium"):
            # Update in file
            fpath = art["fpath"]
            content = fpath.read_text(encoding="utf-8", errors="replace")
            if "confidence:" in content:
                content = re.sub(r"^confidence:.*$", f"confidence: {effective}", content, flags=re.MULTILINE)
            fpath.write_text(content, encoding="utf-8")
            refreshed += 1
            details.append({"id": aid, "old": art.get("confidence"), "new": effective})

    return {"refreshed": refreshed, "details": details}


def generate_report(artifacts: dict | None = None) -> dict:
    """Generate full provenance report."""
    if artifacts is None:
        artifacts = load_all_artifacts()
    now = datetime.now(timezone.utc)

    by_confidence = defaultdict(list)
    by_source = defaultdict(list)
    needs_review = []
    needs_verification = []
    total = len(artifacts)

    for aid, art in artifacts.items():
        if art["status"] in ("archived", "rejected"):
            continue

        effective_conf = compute_confidence(art.get("last_verified", ""), art.get("confidence", "medium"))
        by_confidence[effective_conf].append(aid)
        by_source[art.get("source", "unknown")].append(aid)

        # Review due
        review_due = compute_review_due(art)
        if review_due:
            try:
                due_dt = datetime.strptime(review_due, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_until = (due_dt - now).days
                if days_until < 0:
                    needs_review.append({
                        "id": aid,
                        "type": art["type"],
                        "title": art["title"][:50],
                        "review_due": review_due,
                        "days_overdue": abs(days_until),
                    })
            except ValueError:
                pass

        # Verification staleness
        last_v = art.get("last_verified", "")
        if last_v:
            try:
                v_dt = datetime.fromisoformat(last_v.replace("Z", "+00:00"))
                if v_dt.tzinfo is None:
                    v_dt = v_dt.replace(tzinfo=timezone.utc)
                days_since = (now - v_dt).days
                if days_since > 90:
                    needs_verification.append({
                        "id": aid,
                        "days_since_verification": days_since,
                        "effective_confidence": effective_conf,
                    })
            except (ValueError, TypeError):
                needs_verification.append({
                    "id": aid,
                    "days_since_verification": 9999,
                    "effective_confidence": "outdated",
                })

    needs_review.sort(key=lambda x: x["days_overdue"], reverse=True)
    needs_verification.sort(key=lambda x: x["days_since_verification"], reverse=True)

    return {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "total_artifacts": total,
        "by_confidence": {k: len(v) for k, v in by_confidence.items()},
        "by_source": {k: len(v) for k, v in by_source.items()},
        "needs_review": {
            "count": len(needs_review),
            "items": needs_review[:15],
        },
        "needs_verification": {
            "count": len(needs_verification),
            "items": needs_verification[:15],
        },
        "score": _compute_provenance_score(by_confidence, by_source, total),
    }


def _compute_provenance_score(by_confidence: dict, by_source: dict, total: int) -> int:
    """Compute provenance health score 0-100."""
    if total == 0:
        return 100

    score = 100
    # Penalize outdated/low confidence
    outdated = len(by_confidence.get("outdated", []))
    low = len(by_confidence.get("low", []))
    score -= outdated * 3
    score -= low * 1

    # Bonus for high confidence
    high = len(by_confidence.get("high", []))
    score += high * 1

    # Penalize unknown sources
    unknown = len(by_source.get("unknown", []))
    score -= unknown * 2

    return max(0, min(100, score))


def format_report(report: dict) -> str:
    lines = [
        "═══ ARTIFACT PROVENANCE REPORT ═══",
        f"Generated: {report['timestamp']}",
        f"Total artifacts: {report['total_artifacts']}",
        f"Provenance Score: {report['score']}/100",
        "",
    ]

    lines.append("── Confidence Distribution ──")
    for level in ["high", "medium", "low", "outdated"]:
        count = report["by_confidence"].get(level, 0)
        emoji = "🟢" if level == "high" else "🟡" if level == "medium" else "🟠" if level == "low" else "🔴"
        lines.append(f"  {emoji} {level}: {count}")
    lines.append("")

    lines.append("── Source Distribution ──")
    for source, count in sorted(report["by_source"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  {source}: {count}")
    lines.append("")

    nr = report["needs_review"]
    lines.append(f"── Needs Review: {nr['count']} ──")
    if nr["count"] == 0:
        lines.append("  ✅ All up to date")
    for item in nr["items"][:10]:
        lines.append(f"  🔴 {item['id']} ({item['type']}) — due {item['review_due']} ({item['days_overdue']}d overdue)")
    lines.append("")

    nv = report["needs_verification"]
    lines.append(f"── Needs Verification: {nv['count']} ──")
    if nv["count"] == 0:
        lines.append("  ✅ All verified recently")
    for item in nv["items"][:10]:
        lines.append(f"  ⚠️  {item['id']} — {item['days_since_verification']}d since verification ({item['effective_confidence']})")
    lines.append("")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Artifact provenance tracking")
    parser.add_argument("--verify", type=str, help="Mark artifact as verified today")
    parser.add_argument("--refresh", action="store_true", help="Refresh confidence for all artifacts")
    parser.add_argument("--report", action="store_true", help="Generate provenance report")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.verify:
        result = verify_artifact(args.verify)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif "error" in result:
            print(f"ERROR: {result['error']}")
            sys.exit(1)
        else:
            print(f"✅ Verified {result['id']}: last_verified={result['last_verified']}, confidence={result['confidence']}")
        return

    if args.refresh:
        result = refresh_all_provenance()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Refreshed {result['refreshed']} artifacts")
            for d in result["details"]:
                print(f"  {d['id']}: {d['old']} → {d['new']}")
        return

    # Default: report
    report = generate_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))

    if report["score"] >= 70:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
