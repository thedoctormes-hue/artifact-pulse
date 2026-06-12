#!/usr/bin/env python3
"""audit_report.py — аудит артефактов LabDoctorM: frontmatter, orphans, stale, duplicates."""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from config_loader import get_lab_dir
from normalize_frontmatter import scan, validate, read_text_safe
from artifact_core import parse_frontmatter

BASE = get_lab_dir()
_report_dir_default = BASE / ".qwen/artifacts/audits"
REPORT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else _report_dir_default

# ── 1. Frontmatter validation ──────────────────────
def check_frontmatter():
    try:
        files = scan(str(BASE))
        total = len(files)
        errors_count = 0
        for f in files:
            try:
                content, encoding = read_text_safe(f)
            except Exception:
                errors_count += 1
                continue
            fm, _ = parse_frontmatter(content)
            if not fm:
                errors_count += 1
                continue
            errs, _ = validate(fm, encoding=encoding, fpath=f)
            if errs:
                errors_count += 1
        return {"total_files": total, "errors": errors_count, "ok": errors_count == 0}
    except Exception as e:
        return {"total_files": -1, "errors": -1, "ok": False, "error": str(e)}

# ── 2. Duplicate id detection ──────────────────────
def check_duplicates():
    id_re = re.compile(r"^\s*id:\s*((?:ADR|PAT|RUL|BL|INC|SYS|RPT|MET)-\d+)", re.IGNORECASE)
    id_counts: dict[str, int] = {}
    scan_dirs = [BASE / d for d in ["adr", "patterns", "rules", "specs", "incidents", "docs", "metrics"]]
    for d in scan_dirs:
        if not d.is_dir():
            continue
        for f in d.rglob("*.md"):
            if "template" in f.name.lower():
                continue
            try:
                in_fm = False
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    stripped = line.strip()
                    if stripped == "---":
                        in_fm = not in_fm
                        continue
                    if in_fm:
                        m = id_re.match(line)
                        if m:
                            id_counts[m.group(1).upper()] = id_counts.get(m.group(1).upper(), 0) + 1
            except Exception:
                pass
    dupes = {k: v for k, v in id_counts.items() if v > 1}
    return {"count": len(dupes), "details": dupes, "ok": len(dupes) == 0}

# ── 3. Stale artifacts (>30 days) ──────────────────
def check_stale():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    updated_re = re.compile(r"^\s*updated:\s*(\S+)")
    stale = []
    scan_dirs = [BASE / d for d in ["adr", "patterns", "rules", "specs", "incidents"]]
    for d in scan_dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            if "template" in f.name.lower():
                continue
            try:
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    m = updated_re.match(line)
                    if m:
                        val = m.group(1).strip("\"'")
                        if val < cutoff:
                            stale.append(str(f.relative_to(BASE)))
                        break
            except Exception:
                pass
    return {"stale_30d": len(stale), "details": stale[:10], "ok": len(stale) < 10}

# ── 4. Artifact counts ─────────────────────────────
def check_counts():
    dirs = {
        "adr": BASE / "adr", "patterns": BASE / "patterns",
        "rules": BASE / "rules", "specs": BASE / "specs",
        "incidents": BASE / "incidents", "metrics": BASE / "metrics"
    }
    docs_dir = BASE / "docs"
    docs = len(list(docs_dir.glob("*.md"))) if docs_dir.is_dir() else 0
    reports = len(list((docs_dir / "reports").glob("*.md"))) if (docs_dir / "reports").is_dir() else 0
    result = {}
    for name, path in dirs.items():
        if path.is_dir():
            result[name] = len([f for f in path.glob("*.md") if "template" not in f.name.lower()])
        else:
            result[name] = 0
    result["docs"] = docs
    result["reports"] = reports
    result["total"] = sum(result.values())
    return result

# ── Assembly ────────────────────────────────────────
def main():
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "frontmatter": check_frontmatter(),
            "duplicates": check_duplicates(),
            "stale": check_stale(),
        },
        "counts": check_counts(),
    }
    all_ok = all(v.get("ok", True) for v in report["checks"].values())
    report["overall_ok"] = all_ok

    # Write report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Print summary
    print(json.dumps(report["checks"], indent=2, ensure_ascii=False))
    print(f"\nTotal artifacts: {report['counts']['total']}")
    print(f"Overall: {'✅ OK' if all_ok else '❌ ISSUES FOUND'}")
    print(f"Report: {report_file}")

    # Cleanup old reports (keep last 30)
    old = sorted(REPORT_DIR.glob("audit_*.json"), reverse=True)
    for f in old[30:]:
        f.unlink()

    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
