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

import re
from pathlib import Path
from artifact_core import parse_frontmatter, read_text_safe, validate_frontmatter
from artifact_constants import (
    VALID_STATUSES,
    TYPE_PREFIX,
)

REQUIRED_FIELDS = ["type", "id", "title", "status", "created", "updated"]
VALID_TYPES = list(TYPE_PREFIX.keys())


def validate(fm, encoding="utf-8", fpath=None):
    """Обёртка над validate_frontmatter() для обратной совместимости."""
    return validate_frontmatter(fm, encoding=encoding, fpath=fpath)


def fix_frontmatter(fm: dict, content: str, fpath: Path) -> tuple[bool, list[str]]:
    """Attempt to auto-fix common frontmatter issues.

    Returns (fixed, list_of_applied_fixes).
    Only writes to disk if at least one fix was applied.
    """
    fixes = []
    fm = dict(fm)  # don't mutate original
    modified = False

    # Fix 1: id format — uppercase the prefix if lowercase
    aid = str(fm.get("id", ""))
    atype = str(fm.get("type", ""))
    prefix = TYPE_PREFIX.get(atype, "")
    if aid and prefix and not re.match(rf"^{prefix}-\d{{3,4}}$", aid):
        # Try normalizing: uppercase prefix part
        new_aid = _normalize_id(aid, prefix)
        if new_aid and re.match(rf"^{prefix}-\d{{3,4}}$", new_aid):
            fm["id"] = new_aid
            fixes.append(f"id '{aid}' → '{new_aid}'")
            modified = True

    # Fix 2: invalid status → draft
    valid = VALID_STATUSES.get(atype, [])
    status = str(fm.get("status", ""))
    if valid and status not in valid:
        fm["status"] = "draft"
        fixes.append(f"status '{status}' → 'draft'")
        modified = True

    # Fix 3: created/updated — ensure present and ISO
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for date_field in ("created", "updated"):
        val = fm.get(date_field)
        if not val or str(val).strip() == "":
            fm[date_field] = now_str
            fixes.append(f"{date_field} set to '{now_str}'")
            modified = True

    if not modified:
        return False, []

    # Rebuild frontmatter in content
    new_content = _rebuild_frontmatter(content, fm)
    if new_content:
        fpath.write_text(new_content, encoding="utf-8")

    return True, fixes


def _normalize_id(aid: str, expected_prefix: str) -> str | None:
    """Try to normalize an ID to PREFIX-NNN format."""
    # Strip known bad patterns: spaces, extra dashes
    cleaned = aid.strip().upper()
    # Replace spaces with dashes
    cleaned = cleaned.replace(" ", "-")
    # If prefix is wrong case, fix it
    parts = cleaned.split("-", 1)
    if len(parts) == 2:
        return f"{expected_prefix}-{parts[1]}"
    return None


def _rebuild_frontmatter(content: str, fm: dict) -> str | None:
    """Replace frontmatter in content with corrected fm dict."""
    import io
    try:
        import yaml
    except ImportError:
        return None

    # Split content into frontmatter + body
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return None

    body = match.group(2)

    # Dump new frontmatter
    buf = io.StringIO()
    yaml.dump(fm, buf, default_flow_style=False, allow_unicode=True, sort_keys=False)
    new_fm = buf.getvalue().strip()

    return f"---\n{new_fm}\n---\n{body}"


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
                except Exception:
                    pass
    docs_dir = base / "docs"
    if docs_dir.exists():
        for prefix in ["SYS-", "RPT-", "MET-"]:
            for f in docs_dir.glob(f"{prefix}*.md"):
                try:
                    text, _ = read_text_safe(f)
                    if text.startswith("---"):
                        files.append(f)
                except Exception:
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

        did_fix = False
        if args.fix and errs:
            did_fix, applied = fix_frontmatter(fm, content, f)
            if did_fix:
                fixed_count += 1
                print(f"🔧 {rel}: fixed — {'; '.join(applied)}")
                # Re-validate after fix
                try:
                    new_content, _ = read_text_safe(f)
                    new_fm, _ = parse_frontmatter(new_content)
                    if new_fm:
                        errs, warns = validate(new_fm, encoding=encoding, fpath=f)
                except Exception:
                    pass

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
        print(f"Fixed: {fixed_count}, Remaining errors: {errors_count}, Warnings: {warnings_count}")
