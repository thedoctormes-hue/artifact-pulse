#!/usr/bin/env python3
"""
artifact_aging.py — механизм старения артефактов LabDoctorM.

Правила:
- active артефакт без обновлений > STALE_DAYS (90) и без inbound links → stale
- stale артефакт без обновлений > ARCHIVE_DAYS (180) → archived
- deprecated артефакт > ARCHIVE_DAYS → archived
- Артефакты с inbound links >= 2 никогда не стареют (используются)

Usage:
  python3 artifact_aging.py [--dry-run] [--stale-days N] [--archive-days N] [--json]
"""

import sys
import re
import json
import subprocess
from datetime import datetime, timezone
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import load_all_artifacts as _canonical_load_all
from artifact_constants import (
    REF_PATTERN,
    DEFAULT_STALE_DAYS,
    DEFAULT_ARCHIVE_DAYS,
)

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()


def load_all_artifacts() -> dict:
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def count_inbound_links(artifacts: dict[str, dict]) -> dict[str, int]:
    inbound = {aid: 0 for aid in artifacts}
    for aid, art in artifacts.items():
        body = art.body if hasattr(art, "body") else art.get("_body", "")
        refs = set(REF_PATTERN.findall(body))
        refs.discard(aid)
        for ref in refs:
            if ref in inbound:
                inbound[ref] += 1
    return inbound


def get_inbound_sources(artifacts: dict[str, dict]) -> dict[str, list[str]]:
    """Return mapping: artifact_id → list of IDs that reference it."""
    sources: dict[str, list[str]] = {aid: [] for aid in artifacts}
    for aid, art in artifacts.items():
        body = art.body if hasattr(art, "body") else art.get("_body", "")
        refs = set(REF_PATTERN.findall(body))
        refs.discard(aid)
        for ref in refs:
            if ref in sources:
                sources[ref].append(aid)
    return sources


def analyze_cascade(artifacts: dict[str, dict], details: list[dict]) -> list[dict]:
    """For each aging action, list artifacts that reference the target.

    Returns list of cascade entries:
      [{"target": "ADR-001", "action": "archive", "affected": ["ADR-003", "PAT-002"]}, ...]
    """
    sources = get_inbound_sources(artifacts)
    cascade = []
    for d in details:
        affected = sources.get(d["id"], [])
        if affected:
            cascade.append({
                "target": d["id"],
                "action": d["action"],
                "affected": sorted(affected),
            })
    return cascade


def days_since(date_val) -> int:
    """Compute days since a date value.

    Accepts both str (ISO 8601) and datetime objects.
    datetime objects come from yaml.safe_load parsing of frontmatter.
    """
    if not date_val:
        return 9999
    try:
        if isinstance(date_val, datetime):
            dt = date_val
        else:
            date_str = str(date_val).strip()
            if not date_str:
                return 9999
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError, AttributeError):
        return 9999


def run_aging(dry_run: bool, stale_days: int, archive_days: int) -> dict:
    artifacts = load_all_artifacts()
    inbound = count_inbound_links(artifacts)
    now = datetime.now(timezone.utc)

    results = {
        "checked": 0,
        "staled": 0,
        "archived": 0,
        "skipped": 0,
        "details": [],
    }

    for aid, art in artifacts.items():
        status = str(art.get("status", "")).lower()
        updated = art.get("updated", art.get("created", ""))
        created = art.get("created", "")
        inbound_count = inbound[aid]
        fpath = art.fpath
        fpath_str = str(fpath.relative_to(LAB_DIR))

        results["checked"] += 1

        # Пропускаем уже архивированные
        if status == "archived":
            results["skipped"] += 1
            continue

        # Пропускаем артефакты с >= 2 inbound links (используются)
        if inbound_count >= 2:
            results["skipped"] += 1
            continue

        updated_days = days_since(updated)
        created_days = days_since(created)

        action = None

        # Правило 1: deprecated > ARCHIVE_DAYS → archived
        if status == "deprecated" and created_days > archive_days:
            action = "archive"

        # Правило 2: stale > ARCHIVE_DAYS → archived
        elif status == "stale" and updated_days > archive_days:
            action = "archive"

        # Правило 3: active без inbound > STALE_DAYS → stale
        elif status == "active" and updated_days > stale_days and inbound_count == 0:
            action = "stale"

        # Правило 4: draft > ARCHIVE_DAYS → archived (не были доделаны)
        elif status == "draft" and created_days > archive_days:
            action = "archive"

        if action:
            detail = {
                "id": aid,
                "file": fpath_str,
                "old_status": status,
                "action": action,
                "updated_days": updated_days,
                "inbound": inbound_count,
            }
            results["details"].append(detail)

            if action == "stale":
                results["staled"] += 1
            elif action == "archive":
                results["archived"] += 1

            if not dry_run:
                # Обновляем статус во frontmatter
                content = fpath.read_text(encoding="utf-8", errors="replace")
                new_status = action
                content = re.sub(
                    r"^status:.*$",
                    f"status: {new_status}",
                    content,
                    flags=re.MULTILINE,
                )
                # Добавляем запись об изменении статуса
                aging_note = f"\n\n## Автоматическое старение\nСтатус изменён на `{new_status}` {now.strftime('%Y-%m-%d')}: "
                if action == "stale":
                    aging_note += f"нет обновлений {updated_days} дней, нет входящих ссылок."
                else:
                    aging_note += f"статус `{status}` без активности > {archive_days} дней."
                content = content.rstrip() + aging_note + "\n"
                fpath.write_text(content, encoding="utf-8")

                # Git add
                try:
                    subprocess.run(
                        ["git", "add", str(fpath.relative_to(LAB_DIR))],
                        cwd=LAB_DIR,
                        capture_output=True,
                        timeout=10,
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

    return results


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    json_output = "--json" in args
    cascade = "--cascade" in args
    stale_days = DEFAULT_STALE_DAYS
    archive_days = DEFAULT_ARCHIVE_DAYS

    for i, a in enumerate(args):
        if a == "--stale-days" and i + 1 < len(args):
            stale_days = int(args[i + 1])
        if a == "--archive-days" and i + 1 < len(args):
            archive_days = int(args[i + 1])

    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"artifact_aging.py — {mode}")
    print(f"  stale threshold: {stale_days} days")
    print(f"  archive threshold: {archive_days} days")
    if cascade:
        print("  cascade analysis: ON")
    print()

    results = run_aging(dry_run, stale_days, archive_days)

    cascade_results = []
    if cascade and results["details"]:
        artifacts = load_all_artifacts()
        cascade_results = analyze_cascade(artifacts, results["details"])
        results["cascade"] = cascade_results

    if json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    print(f"Checked: {results['checked']}")
    print(f"Skipped: {results['skipped']}")
    print(f"To stale: {results['staled']}")
    print(f"To archive: {results['archived']}")
    print()

    if results["details"]:
        print("Actions:")
        for d in results["details"]:
            print(f"  {d['action']:<10} {d['id']:<12} ({d['old_status']:<10}) {d['file']}")
            print(f"             updated {d['updated_days']}d ago, inbound: {d['inbound']}")
    else:
        print("No aging actions needed.")

    if cascade_results:
        print()
        print("Cascade analysis — affected references:")
        for c in cascade_results:
            print(f"  {c['action']:<10} {c['target']:<12} → affects: {', '.join(c['affected'])}")


if __name__ == "__main__":
    main()
