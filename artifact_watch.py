#!/usr/bin/env python3
"""
artifact_watch.py — планировщик проверок здоровья артефактов LabDoctorM.

Запускает health check по расписанию, выводит только алерты.
Если алертов нет — молчит (exit 0). Есть — компактный список (exit 1).

Режимы:
- --once: однократная проверка (для systemd timer)
- --interval N: цикл с интервалом в минутах (для ручного запуска)

Usage:
  python3 artifact_watch.py [--once] [--interval MINUTES] [--json]
"""

import sys
import json
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from config_loader import get_lab_dir, get_state_file
from artifact_health import (
    load_all_artifacts, check_frontmatter, check_links, check_aging,
    check_duplicates, check_code_refs, check_insights_queue,
    check_infrastructure, check_provenance_dimension, check_constraints_dimension,
    compute_overall_score,
)
from artifact_monitor import run_health_snapshot, compute_trends, check_alerts, check_alerts, load_history  # noqa: F401
from artifact_constants import (
    ALERT_WARN_SCORE,
    ALERT_CRIT_SCORE,
)
from artifact_core import load_all_artifacts as _canonical_load_all

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS_CACHE: dict = {}


def _get_artifacts():
    if not ARTIFACT_DIRS_CACHE:
        from config_loader import get_artifact_dirs
        ARTIFACT_DIRS_CACHE.update(get_artifact_dirs())
    return _canonical_load_all(ARTIFACT_DIRS_CACHE, LAB_DIR)


def run_watch_once(json_output: bool = False) -> int:
    """Run single health check, print alerts if any. Returns exit code."""
    snapshot = run_health_snapshot()

    history_file = get_state_file("health_history") or LAB_DIR / ".qwen/artifacts/health_history.jsonl"
    from artifact_monitor import load_history, compute_trends as _compute_trends, check_alerts as _check_alerts
    history = load_history(30)
    trends = _compute_trends(history)
    alerts = _check_alerts(snapshot, trends)

    if alerts:
        if json_output:
            print(json.dumps({
                "timestamp": snapshot["timestamp"],
                "score": snapshot["overall_score"],
                "alerts": alerts,
            }, ensure_ascii=False, indent=2))
        else:
            score = snapshot["overall_score"]
            emoji = "🔴" if score < ALERT_CRIT_SCORE else "🟡"
            print(f"{emoji} Health: {score}/100 | {len(alerts)} alert(s)")
            for a in alerts:
                level = "CRIT" if a["level"] == "CRITICAL" else "WARN"
                print(f"  [{level}] {a['message']}")
        return 1

    if json_output:
        print(json.dumps({
            "timestamp": snapshot["timestamp"],
            "score": snapshot["overall_score"],
            "alerts": [],
        }, ensure_ascii=False, indent=2))

    return 0


def run_watch_loop(interval_minutes: int):
    """Run health check loop with specified interval."""
    print(f"artifact-watch: checking every {interval_minutes} min (Ctrl+C to stop)")
    while True:
        try:
            code = run_watch_once()
            if code != 0:
                print()
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
        time.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="Artifact health watch scheduler")
    parser.add_argument("--once", action="store_true", help="Single check (for systemd timer)")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in minutes (default: 60)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.once or args.interval is None:
        sys.exit(run_watch_once(args.json))
    else:
        run_watch_loop(args.interval)


if __name__ == "__main__":
    main()
