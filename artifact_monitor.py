#!/usr/bin/env python3
"""
artifact_monitor.py — непрерывный мониторинг здоровья системы артефактов.

Отслеживает тренды качества во времени, генерирует алерты при деградации,
сохраняет историю измерений для визуализации трендов.

Хранит историю в .qwen/artifacts/health_history.jsonl (одна запись на запуск).
Поддерживает:
- Сравнение с предыдущими измерениями
- Алерты при падении скора ниже порога
- Алерты при появлении новых broken links
- Алерты при деградации confidence
- Генерация сводного отчёта с трендами

Usage:
  python3 artifact_monitor.py [--check] [--trends] [--alerts-only] [--json]
  python3 artifact_monitor.py --history [--days N]
"""

import sys
import json
from datetime import datetime, timezone, timedelta
from config_loader import get_lab_dir, get_state_file
from artifact_health import (
    load_all_artifacts, check_frontmatter, check_links, check_aging,
    check_duplicates, check_code_refs, check_insights_queue,
    check_infrastructure, compute_overall_score,
)
from artifact_provenance import generate_report as provenance_report
from artifact_constraints import run_all_checks as constraint_checks
from artifact_constants import (
    ALERT_WARN_SCORE,
    ALERT_CRIT_SCORE,
    ALERT_BROKEN_LINKS,
    ALERT_ORPHANS,
    ALERT_OUTDATED_PCT,
    HISTORY_MAX_ENTRIES,
    HISTORY_MAX_DAYS,
)

LAB_DIR = get_lab_dir()
HISTORY_FILE = get_state_file("health_history") or LAB_DIR / ".qwen/artifacts/health_history.jsonl"
ALERTS_FILE = get_state_file("alerts") or LAB_DIR / ".qwen/artifacts/alerts.json"
TRENDS_FILE = get_state_file("trends") or LAB_DIR / ".qwen/artifacts/trends.json"


def run_health_snapshot() -> dict:
    """Run a full health check and return snapshot."""
    artifacts = load_all_artifacts()

    checks = {
        "frontmatter": check_frontmatter(artifacts),
        "links": check_links(artifacts),
        "aging": check_aging(artifacts),
        "duplicates": check_duplicates(artifacts),
        "code_refs": check_code_refs(artifacts),
        "insights": check_insights_queue(),
        "infrastructure": check_infrastructure(),
    }
    overall = compute_overall_score(checks)

    # Provenance (reuse already-loaded artifacts)
    prov_report = provenance_report(artifacts)

    # Constraints (reuse already-loaded artifacts)
    constraint_report = constraint_checks(artifacts)

    snapshot = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "overall_score": overall,
        "checks": checks,
        "provenance_score": prov_report.get("score", 0),
        "constraint_score": constraint_report.get("score", 0),
        "total_artifacts": len(artifacts),
        "broken_links": checks["links"]["broken_count"],
        "orphans": checks["links"]["orphan_count"],
        "stale": checks["aging"]["stale_count"],
        "outdated_confidence": prov_report.get("by_confidence", {}).get("outdated", 0),
        "constraint_errors": constraint_report.get("errors", 0),
        "constraint_warnings": constraint_report.get("warnings", 0),
    }

    return snapshot


def _rotate_history():
    """Trim history file to HISTORY_MAX_ENTRIES and HISTORY_MAX_DAYS."""
    if not HISTORY_FILE.exists():
        return
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= 1:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_MAX_DAYS)
    needs_rotate = len(lines) > HISTORY_MAX_ENTRIES
    if not needs_rotate:
        # Check if any entry exceeds age limit
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entry_dt = datetime.fromisoformat(entry["timestamp"].replace("+00:00", "+00:00"))
                if entry_dt < cutoff:
                    needs_rotate = True
                    break
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    if not needs_rotate:
        return

    kept = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry_dt = datetime.fromisoformat(entry["timestamp"].replace("+00:00", "+00:00"))
            if entry_dt >= cutoff and len(kept) < HISTORY_MAX_ENTRIES:
                kept.append(line)
        except (json.JSONDecodeError, KeyError, ValueError):
            kept.append(line)  # keep unparseable lines to avoid data loss

    kept.reverse()
    HISTORY_FILE.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")


def save_snapshot(snapshot: dict):
    """Append snapshot to history file, then rotate."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    _rotate_history()


def load_history(days: int = 30) -> list:
    """Load health history for the last N days."""
    if not HISTORY_FILE.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    history = []

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entry_dt = datetime.fromisoformat(entry["timestamp"].replace("+00:00", "+00:00"))
                if entry_dt >= cutoff:
                    history.append(entry)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    return history


def compute_trends(history: list) -> dict:
    """Compute trends from history."""
    if len(history) < 2:
        return {"status": "insufficient_data", "message": "Need at least 2 data points"}

    first = history[0]
    last = history[-1]

    score_trend = last["overall_score"] - first["overall_score"]
    artifact_trend = last["total_artifacts"] - first["total_artifacts"]
    broken_trend = last["broken_links"] - first["broken_links"]
    orphan_trend = last["orphans"] - first["orphans"]

    # Compute velocity (change per day)
    try:
        first_dt = datetime.fromisoformat(first["timestamp"].replace("+00:00", "+00:00"))
        last_dt = datetime.fromisoformat(last["timestamp"].replace("+00:00", "+00:00"))
        days_diff = max((last_dt - first_dt).days, 1)
    except (ValueError, TypeError):
        days_diff = 1

    score_velocity = round(score_trend / days_diff, 2)

    # Determine trend direction
    if score_trend > 5:
        direction = "improving"
    elif score_trend < -5:
        direction = "degrading"
    else:
        direction = "stable"

    # Score history for sparkline
    score_history = [(e["timestamp"][:10], e["overall_score"]) for e in history]

    return {
        "period_days": days_diff,
        "data_points": len(history),
        "score": {
            "current": last["overall_score"],
            "previous": first["overall_score"],
            "change": score_trend,
            "velocity_per_day": score_velocity,
            "direction": direction,
        },
        "artifacts": {
            "current": last["total_artifacts"],
            "change": artifact_trend,
        },
        "broken_links": {
            "current": last["broken_links"],
            "change": broken_trend,
        },
        "orphans": {
            "current": last["orphans"],
            "change": orphan_trend,
        },
        "score_history": score_history,
    }


def check_alerts(snapshot: dict, trends: dict) -> list:
    """Generate alerts based on snapshot and trends."""
    alerts = []

    # Score-based alerts
    if snapshot["overall_score"] < ALERT_CRIT_SCORE:
        alerts.append({
            "level": "CRITICAL",
            "type": "LOW_HEALTH_SCORE",
            "message": f"Health score {snapshot['overall_score']} below critical threshold {ALERT_CRIT_SCORE}",
            "value": snapshot["overall_score"],
        })
    elif snapshot["overall_score"] < ALERT_WARN_SCORE:
        alerts.append({
            "level": "WARNING",
            "type": "LOW_HEALTH_SCORE",
            "message": f"Health score {snapshot['overall_score']} below warning threshold {ALERT_WARN_SCORE}",
            "value": snapshot["overall_score"],
        })

    # Broken links alert
    if snapshot["broken_links"] >= ALERT_BROKEN_LINKS:
        alerts.append({
            "level": "WARNING",
            "type": "BROKEN_LINKS",
            "message": f"{snapshot['broken_links']} broken links (threshold: {ALERT_BROKEN_LINKS})",
            "value": snapshot["broken_links"],
        })

    # Orphans alert
    if snapshot["orphans"] >= ALERT_ORPHANS:
        alerts.append({
            "level": "WARNING",
            "type": "ORPHAN_ARTIFACTS",
            "message": f"{snapshot['orphans']} orphan artifacts (threshold: {ALERT_ORPHANS})",
            "value": snapshot["orphans"],
        })

    # Outdated confidence
    total = snapshot.get("total_artifacts", 1)
    outdated_pct = snapshot.get("outdated_confidence", 0) / max(total, 1) * 100
    if outdated_pct > ALERT_OUTDATED_PCT:
        alerts.append({
            "level": "WARNING",
            "type": "OUTDATED_CONFIDENCE",
            "message": f"{outdated_pct:.0f}% artifacts have outdated confidence",
            "value": outdated_pct,
        })

    # Trend-based alerts
    if trends.get("status") != "insufficient_data":
        if trends["score"]["direction"] == "degrading":
            alerts.append({
                "level": "WARNING",
                "type": "DEGRADING_TREND",
                "message": f"Health score degrading: {trends['score']['velocity_per_day']}/day over {trends['period_days']} days",
                "value": trends["score"]["velocity_per_day"],
            })

    # Constraint alerts
    if snapshot.get("constraint_errors", 0) > 0:
        alerts.append({
            "level": "WARNING",
            "type": "CONSTRAINT_ERRORS",
            "message": f"{snapshot['constraint_errors']} constraint violations",
            "value": snapshot["constraint_errors"],
        })

    return alerts


def format_trends(trends: dict) -> str:
    if trends.get("status") == "insufficient_data":
        return f"  Trends: {trends['message']}"

    s = trends["score"]
    emoji = "📈" if s["direction"] == "improving" else "📉" if s["direction"] == "degrading" else "➡️"

    lines = [
        f"  {emoji} Score: {s['current']} (was {s['previous']}, change: {s['change']:+d}, {s['velocity_per_day']:+.2f}/day)",
        f"  📦 Artifacts: {trends['artifacts']['current']} (change: {trends['artifacts']['change']:+d})",
        f"  🔗 Broken links: {trends['broken_links']['current']} (change: {trends['broken_links']['change']:+d})",
        f"  👻 Orphans: {trends['orphans']['current']} (change: {trends['orphans']['change']:+d})",
    ]

    # Sparkline
    if trends.get("score_history"):
        scores = [s for _, s in trends["score_history"]]
        if scores:
            min_s, max_s = min(scores), max(scores)
            range_s = max(max_s - min_s, 1)
            blocks = "▁▂▃▄▅▆▇█"
            sparkline = ""
            for sc in scores[-20:]:  # last 20 points
                idx = int((sc - min_s) / range_s * (len(blocks) - 1))
                idx = max(0, min(idx, len(blocks) - 1))
                sparkline += blocks[idx]
            lines.append(f"  📊 Sparkline: {sparkline}")

    return "\n".join(lines)


def format_alerts(alerts: list) -> str:
    if not alerts:
        return "  ✅ No alerts — all clear!"

    lines = []
    for a in alerts:
        emoji = "🔴" if a["level"] == "CRITICAL" else "🟡"
        lines.append(f"  {emoji} [{a['level']}] {a['message']}")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Continuous artifact monitoring")
    parser.add_argument("--check", action="store_true", help="Run health check and save snapshot")
    parser.add_argument("--trends", action="store_true", help="Show trends")
    parser.add_argument("--alerts-only", action="store_true", help="Only show alerts")
    parser.add_argument("--history", action="store_true", help="Show history")
    parser.add_argument("--days", type=int, default=30, help="History period in days")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--rotate", action="store_true", help="Rotate history file and exit")
    args = parser.parse_args()

    if args.rotate:
        before = 0
        if HISTORY_FILE.exists():
            before = len(HISTORY_FILE.read_text(encoding="utf-8").splitlines())
        _rotate_history()
        after = 0
        if HISTORY_FILE.exists():
            after = len([line for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines() if line.strip()])
        print(f"Rotation complete: {before} → {after} entries (max {HISTORY_MAX_ENTRIES}, {HISTORY_MAX_DAYS}d)")
        return

    if args.history:
        history = load_history(args.days)
        if args.json:
            print(json.dumps(history, ensure_ascii=False, indent=2))
        else:
            print(f"Health History (last {args.days} days, {len(history)} entries):")
            for entry in history:
                ts = entry["timestamp"][:16]
                score = entry["overall_score"]
                artifacts = entry["total_artifacts"]
                broken = entry["broken_links"]
                print(f"  {ts}  score={score:3d}  artifacts={artifacts:3d}  broken={broken}")
        return

    # Default: run check
    snapshot = run_health_snapshot()
    save_snapshot(snapshot)

    history = load_history(args.days)
    trends = compute_trends(history)
    alerts = check_alerts(snapshot, trends)

    # Save alerts
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    alerts_data = {
        "timestamp": snapshot["timestamp"],
        "alerts": alerts,
        "snapshot_score": snapshot["overall_score"],
    }
    ALERTS_FILE.write_text(json.dumps(alerts_data, ensure_ascii=False, indent=2))

    # Save trends
    TRENDS_FILE.write_text(json.dumps(trends, ensure_ascii=False, indent=2))

    if args.json:
        output = {
            "snapshot": snapshot,
            "trends": trends,
            "alerts": alerts,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    if args.alerts_only:
        print(format_alerts(alerts))
        return

    # Full report
    status_emoji = "🟢" if snapshot["overall_score"] >= 80 else "🟡" if snapshot["overall_score"] >= 60 else "🔴"
    print("═══ ARTIFACT MONITOR ═══")
    print(f"Timestamp: {snapshot['timestamp']}")
    print(f"{status_emoji} Health Score: {snapshot['overall_score']}/100")
    print(f"Artifacts: {snapshot['total_artifacts']} | Broken: {snapshot['broken_links']} | Orphans: {snapshot['orphans']}")
    print(f"Provenance: {snapshot['provenance_score']}/100 | Constraints: {snapshot['constraint_score']}/100")
    print()

    print("── Trends ──")
    print(format_trends(trends))
    print()

    print(f"── Alerts ({len(alerts)}) ──")
    print(format_alerts(alerts))
    print()

    # Exit code
    if any(a["level"] == "CRITICAL" for a in alerts):
        sys.exit(2)
    elif alerts:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
