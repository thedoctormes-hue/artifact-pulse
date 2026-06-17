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
  python3 normalize_frontmatter.py [--check] [--fix] [--fix-all] [--path PATH]

  --check     Validate only (default)
  --fix       Fix critical errors (id, status, created, updated)
  --fix-all   Full fix: also auto-detect source, set last_verified
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from artifact_core import parse_frontmatter, read_text_safe, validate_frontmatter
from artifact_constants import (
    VALID_STATUSES,
    TYPE_PREFIX,
)

REQUIRED_FIELDS = ["type", "id", "title", "status", "created", "updated"]
VALID_TYPES = list(TYPE_PREFIX.keys())

# Agent authors — if author matches one of these, source defaults to "agent"
AGENT_AUTHORS = {"owl", "kotolizator", "bestia", "mangust", "streikbrecher", "antcat"}


def validate(fm, encoding="utf-8", fpath=None):
    """Обёртка над validate_frontmatter() для обратной совместимости."""
    return validate_frontmatter(fm, encoding=encoding, fpath=fpath)


def fix_frontmatter(
    fm: dict, content: str, fpath: Path, fix_all: bool = False
) -> tuple[bool, list[str]]:
    """Attempt to auto-fix common frontmatter issues.

    Args:
        fm: frontmatter dict
        content: full file content
        fpath: path to file
        fix_all: if True, also apply non-essential fixes (source, last_verified)

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

    # Fix 3: created — if missing, try updated, then file creation time
    created_val = fm.get("created")
    if not created_val or str(created_val).strip() == "":
        # Try updated first
        updated_val = fm.get("updated")
        if updated_val and str(updated_val).strip() != "":
            fm["created"] = updated_val
            fixes.append(f"created ← updated ('{updated_val}')")
        else:
            # Fall back to file creation time
            try:
                ctime = os.path.getctime(fpath)
                ctime_str = datetime.fromtimestamp(ctime, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                )
                fm["created"] = ctime_str
                fixes.append(f"created ← file ctime ('{ctime_str}')")
            except OSError:
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                fm["created"] = now_str
                fixes.append(f"created ← now ('{now_str}')")
        modified = True

    # Fix 3b: updated — ensure present
    updated_val = fm.get("updated")
    if not updated_val or str(updated_val).strip() == "":
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fm["updated"] = now_str
        fixes.append(f"updated set to '{now_str}'")
        modified = True

    # Fix 4: source — auto-detect from author (only with --fix-all)
    if fix_all:
        author_val = str(fm.get("author", "")).strip().lower()
        if author_val in AGENT_AUTHORS:
            expected_source = "agent"
        else:
            expected_source = "manual"
        current_source = str(fm.get("source", "")).strip()
        if current_source != expected_source:
            fm["source"] = expected_source
            fixes.append(f"source ← '{expected_source}' (author: {author_val})")
            modified = True

        # Fix 5: last_verified — set to today (only with --fix-all)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        current_verified = str(fm.get("last_verified", "")).strip()
        if current_verified != today_str:
            fm["last_verified"] = today_str
            fixes.append(f"last_verified ← '{today_str}'")
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
    dirs_to_scan = [
        base / d for d in ["adr", "patterns", "rules", "incidents", "specs", "metrics"]
    ]
    files = []
    for d in dirs_to_scan:
        if d.exists():
            for f in d.rglob("*.md"):
                if (
                    "README" in f.name
                    or "UPGRADE" in f.name
                    or "template" in f.name.lower()
                ):
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
    parser = argparse.ArgumentParser(
        description="Нормализация frontmatter артефактов LabDoctorM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Режимы:
  --check     Только проверка (по умолчанию)
  --fix        Автофикс критических ошибок (id, status, created, updated)
  --fix-all    Полный автофикс (включая source, last_verified)
        """,
    )
    parser.add_argument(
        "--check", action="store_true", help="Только проверка, без исправлений"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Автофикс критических ошибок"
    )
    parser.add_argument(
        "--fix-all",
        action="store_true",
        help="Полный автофикт: source, last_verified + --fix",
    )
    parser.add_argument(
        "--path", default=_default_path, help=f"Базовый путь (default: {_default_path})"
    )
    args = parser.parse_args()

    # --fix-all включает и --fix
    do_fix = args.fix or args.fix_all
    fix_all = args.fix_all
    check_only = not do_fix

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
        if do_fix and errs:
            did_fix, applied = fix_frontmatter(fm, content, f, fix_all=fix_all)
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
        print(
            f"Fixed: {fixed_count}, Remaining errors: {errors_count}, Warnings: {warnings_count}"
        )
