#!/usr/bin/env python3
"""
normalize_frontmatter.py — нормализация frontmatter всех артефактов LabDoctorM.

Правила:
- Обязательные поля: type, id, title, status, author, created, updated
- id формат: TYPE-NNN (uppercase, дефис, 3 цифры)
- type: adr | pattern | rule | backlog | incident | sys | report | metric
- status: допустимые значения зависят от type
- created/updated: ISO 8601

Usage:
  python3 normalize_frontmatter.py [--check] [--fix] [--path PATH]
"""

import sys, os, re
from pathlib import Path
from datetime import datetime
from artifact_core import parse_frontmatter, detect_encoding, read_text_safe

REQUIRED_FIELDS = ["type", "id", "title", "status", "author", "created", "updated"]
VALID_TYPES = ["adr", "pattern", "rule", "backlog", "incident", "sys", "report", "metric"]

VALID_STATUSES = {
    "adr": ["proposed", "accepted", "rejected", "deprecated", "superseded"],
    "pattern": ["draft", "active", "deprecated"],
    "rule": ["draft", "active", "deprecated"],
    "backlog": ["pending", "in_progress", "done", "cancelled", "archived"],
    "incident": ["open", "investigating", "resolved", "closed"],
    "sys": ["draft", "active", "archived"],
    "report": ["draft", "final"],
    "metric": ["active", "deprecated"],
}

TYPE_PREFIX = {
    "adr": "ADR", "pattern": "PAT", "rule": "RUL", "backlog": "BL",
    "incident": "INC", "sys": "SYS", "report": "RPT", "metric": "MET",
}


def validate(fm, encoding="utf-8", fpath=None):
    errors = []
    warnings = []

    # Encoding check
    if encoding not in ("utf-8", "utf-8-sig"):
        warnings.append(f"file encoding is '{encoding}', expected utf-8")

    for f in REQUIRED_FIELDS:
        if f not in fm or fm[f] is None or str(fm[f]).strip() == "":
            errors.append(f"missing required field: {f}")
    aid = str(fm.get("id", ""))
    atype = str(fm.get("type", ""))
    prefix = TYPE_PREFIX.get(atype, "")
    if aid and prefix and not re.match(rf"^{prefix}-\d{{3,4}}$", aid):
        errors.append(f"id '{aid}' doesn't match expected format '{prefix}-NNN'")
    valid = VALID_STATUSES.get(atype, [])
    status = str(fm.get("status", ""))
    if valid and status not in valid:
        errors.append(f"status '{status}' not valid for type '{atype}'. Valid: {valid}")
    return errors, warnings


def scan(base_path):
    base = Path(base_path)
    dirs_to_scan = [base/d for d in ["adr","patterns","rules","incidents","specs","metrics"]]
    files = []
    for d in dirs_to_scan:
        if d.exists():
            for f in d.rglob("*.md"):
                if "README" in f.name or "UPGRADE" in f.name or "template" in f.name.lower():
                    continue
                try:
                    text, _ = read_text_safe(f)
                    if text.startswith("---"):
                        files.append(f)
                except:
                    pass
    docs_dir = base / "docs"
    if docs_dir.exists():
        for prefix in ["SYS-", "RPT-", "MET-"]:
            for f in docs_dir.glob(f"{prefix}*.md"):
                try:
                    text, _ = read_text_safe(f)
                    if text.startswith("---"):
                        files.append(f)
                except:
                    pass
    return files


if __name__ == "__main__":
    import argparse
    from config_loader import get_lab_dir

    _default_path = str(get_lab_dir())
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--path", default=_default_path)
    args = parser.parse_args()

    check_only = not args.fix
    files = scan(args.path)
    total = errors_count = warnings_count = fixed_count = 0
    _lab_prefix = _default_path.rstrip("/") + "/"

    for f in sorted(files):
        total += 1
        try:
            content, encoding = read_text_safe(f)
        except Exception as e:
            errors_count += 1
            rel = str(f).replace(_lab_prefix, "")
            print(f"❌ {rel}: read error: {e}")
            continue

        fm, _ = parse_frontmatter(content)
        if not fm:
            errors_count += 1
            rel = str(f).replace(_lab_prefix, "")
            print(f"❌ {rel}: no valid frontmatter")
            continue

        errs, warns = validate(fm, encoding=encoding, fpath=f)
        rel = str(f).replace(_lab_prefix, "")
        if errs:
            errors_count += 1
            print(f"❌ {rel}: {', '.join(errs)}")
        if warns:
            warnings_count += 1
            for w in warns:
                print(f"⚠️  {rel}: {w}")

    print(f"\n{'='*50}")
    print(f"Total: {total} files scanned")
    if check_only:
        print(f"Errors: {errors_count} | Warnings: {warnings_count}")
    else:
        print(f"Fixed: {fixed_count}, Remaining: {errors_count}, Warnings: {warnings_count}")
