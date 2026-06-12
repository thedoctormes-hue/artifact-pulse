#!/usr/bin/env python3
"""
artifact_stats.py — статистика и рейтинг артефактов LabDoctorM.

Отслеживает:
- Количество цитирований артефакта другими артефактами (inbound links)
- Количество исходящих ссылок (outbound links)
- Возраст артефакта (дней с создания)
- Комбинированный рейтинг полезности

Usage:
  python3 artifact_stats.py [--update] [--top N] [--json]
"""

import sys
import json
from datetime import datetime, timezone
from config_loader import get_lab_dir, get_artifact_dirs, get_state_file
from artifact_core import (
    load_all_artifacts as _canonical_load_all,
)
from artifact_constants import REF_PATTERN_LOOSE as REF_PATTERN

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()
STATS_FILE = get_state_file("artifact_stats") or LAB_DIR / ".qwen/artifacts/artifact_stats.json"


def load_all_artifacts() -> dict:
    """Load all artifacts keyed by their ID."""
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def compute_stats(artifacts: dict[str, dict]) -> dict:
    """Compute citation graph and stats."""
    # Find all references between artifacts
    inbound = {aid: [] for aid in artifacts}
    outbound = {aid: [] for aid in artifacts}

    for aid, art in artifacts.items():
        body = art.body
        refs = set(REF_PATTERN.findall(body))
        refs.discard(aid)  # skip self-references
        for ref in refs:
            if ref in artifacts:
                outbound[aid].append(ref)
                inbound[ref].append(aid)

    # Compute scores
    now = datetime.now(timezone.utc)
    stats = {}

    for aid, art in artifacts.items():
        created_str = art.get("created", "")
        age_days = 0
        if created_str:
            try:
                created = datetime.fromisoformat(str(created_str).replace("+00:00", "+00:00"))
                age_days = (now - created).days
            except (ValueError, TypeError):
                pass

        confirmations = int(art.get("confirmations", 0) or 0)
        in_count = len(inbound[aid])
        out_count = len(outbound[aid])
        status = str(art.get("status", "")).lower()

        # Composite score
        score = 0.0
        score += confirmations * 5.0
        score += in_count * 3.0  # cited by others = useful
        score += min(age_days / 30.0, 10.0)  # older = more established, cap at 10

        # Status multiplier
        if status == "active":
            score *= 1.2
        elif status == "deprecated":
            score *= 0.3
        elif status == "draft":
            score *= 0.7

        stats[aid] = {
            "id": aid,
            "type": art.type,
            "title": art.get("title", "?")[:60],
            "status": art.get("status", "?"),
            "confirmations": confirmations,
            "inbound": in_count,
            "outbound": out_count,
            "inbound_from": inbound[aid],
            "outbound_to": outbound[aid],
            "age_days": age_days,
            "score": round(score, 1),
            "file": art.file,
        }

    return stats


def update_stats():
    """Recompute and save stats."""
    artifacts = load_all_artifacts()
    stats = compute_stats(artifacts)

    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(
        json.dumps(
            {
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "total_artifacts": len(artifacts),
                "artifacts": stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print(f"Stats updated: {len(artifacts)} artifacts → {STATS_FILE}")
    return stats


def show_top(stats: dict, n: int = 10, json_output: bool = False):
    """Show top N artifacts by score."""
    sorted_stats = sorted(stats.values(), key=lambda x: x["score"], reverse=True)[:n]

    if json_output:
        print(json.dumps(sorted_stats, ensure_ascii=False, indent=2))
        return

    print(f"{'Rank':<5} {'Score':<7} {'ID':<12} {'Type':<10} {'Status':<10} {'In':<4} {'Conf':<5} {'Title'}")
    print("-" * 90)

    for i, s in enumerate(sorted_stats, 1):
        print(
            f"{i:<5} {s['score']:<7.1f} {s['id']:<12} {s['type']:<10} "
            f"{s['status']:<10} {s['inbound']:<4} {s['confirmations']:<5} {s['title']}"
        )

    # Summary
    by_type = {}
    for s in stats.values():
        t = s["type"]
        by_type[t] = by_type.get(t, 0) + 1

    print()
    print("By type:", ", ".join(f"{t}: {c}" for t, c in sorted(by_type.items())))

    # Orphans (no inbound, no outbound)
    orphans = [s for s in stats.values() if s["inbound"] == 0 and s["outbound"] == 0]
    print(f"Orphans (no links): {len(orphans)}")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    update = "--update" in args
    json_output = "--json" in args
    top_n = 10

    for i, a in enumerate(args):
        if a == "--top" and i + 1 < len(args):
            top_n = int(args[i + 1])

    if update or not STATS_FILE.exists():
        stats = update_stats()
    else:
        data = json.loads(STATS_FILE.read_text())
        stats = data.get("artifacts", {})

    show_top(stats, top_n, json_output)


if __name__ == "__main__":
    main()
