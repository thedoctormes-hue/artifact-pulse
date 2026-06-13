"""artifact_core.py — общие функции для всех модулей Artifact Pulse.

Содержит:
- parse_frontmatter() — парсинг YAML frontmatter из .md файлов (yaml.safe_load)
- load_artifact_file() — загрузка одного артефакта
- detect_encoding() / read_text_safe() — детекция кодировки
- validate_frontmatter() — единая валидация frontmatter (используется health, normalize, audit)
"""

import re
import yaml
from pathlib import Path
from typing import Optional

from artifact_constants import (
    ID_PATTERN,
    TEMPLATE_NAMES,
    VALID_STATUSES,
    TYPE_PREFIX,
)
from artifact_types import Artifact

# ── Frontmatter ────────────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content using yaml.safe_load.

    Returns:
        (metadata_dict, body_string)
    """
    if not content.startswith("---"):
        return {}, content

    end = content.find("---", 3)
    if end == -1:
        return {}, content

    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()

    try:
        metadata = yaml.safe_load(fm_text) or {}
        if not isinstance(metadata, dict):
            metadata, body = {}, content
    except yaml.YAMLError:
        metadata = {}

    return metadata, body


def parse_frontmatter_with_raw(content: str) -> tuple[dict, str, str]:
    """Parse YAML frontmatter, also returns raw frontmatter text.

    Returns:
        (metadata_dict, body_string, raw_frontmatter_string)
    """
    if not content.startswith("---"):
        return {}, content, ""

    end = content.find("---", 3)
    if end == -1:
        return {}, content, ""

    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()

    try:
        metadata = yaml.safe_load(fm_text) or {}
        if not isinstance(metadata, dict):
            metadata, body, fm_text = {}, content, ""
    except yaml.YAMLError:
        metadata = {}

    return metadata, body, fm_text


# ── Encoding detection ─────────────────────────────────────────

def detect_encoding(fpath: Path) -> str:
    """Detect file encoding. Returns encoding name.

    Strategy:
    1. Try UTF-8 (strict) — most common
    2. Check for BOM (UTF-16/UTF-32)
    3. Fallback: latin-1 (never fails, maps bytes 1:1)
    """
    raw = fpath.read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return 'utf-16'
    if raw.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass
    return 'latin-1'


def read_text_safe(fpath: Path) -> tuple:
    """Read file with encoding detection. Returns (text, encoding_used)."""
    enc = detect_encoding(fpath)
    try:
        return fpath.read_text(encoding=enc), enc
    except (OSError, UnicodeDecodeError):
        return fpath.read_bytes().decode('latin-1', errors='replace'), 'latin-1-fallback'


# ── Unified Validation ─────────────────────────────────────────

def validate_frontmatter(fm: dict, encoding: str = "utf-8", fpath=None) -> tuple[list[str], list[str]]:
    """Единая функция валидации frontmatter для всех модулей.

    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if encoding not in ("utf-8", "utf-8-sig"):
        warnings.append(f"file encoding is '{encoding}', expected utf-8")

    aid = str(fm.get("id", ""))
    atype = str(fm.get("type", ""))
    status = str(fm.get("status", ""))

    # Required fields
    required = ["type", "id", "title", "status", "created", "updated"]
    for field in required:
        val = fm.get(field)
        if val is None or str(val).strip() == "":
            errors.append(f"missing required field: {field}")

    # ID format
    prefix = TYPE_PREFIX.get(atype, "")
    if aid and prefix and not re.match(rf"^{re.escape(prefix)}-\d{{3,4}}$", aid):
        errors.append(f"id '{aid}' doesn't match expected format '{prefix}-NNN'")

    # Status validity
    valid = VALID_STATUSES.get(atype, [])
    if valid and status not in valid:
        errors.append(f"status '{status}' not valid for type '{atype}'. Valid: {valid}")

    return errors, warnings


# ── File loading ───────────────────────────────────────────────

def load_artifact_file(fpath: Path) -> Optional[dict]:
    """Load a single artifact file and return parsed dict.

    Returns None if file cannot be parsed.
    """
    try:
        content, encoding = read_text_safe(fpath)
    except Exception:
        return None

    meta, body = parse_frontmatter(content)
    if not meta:
        return None

    return {
        "meta": meta,
        "body": body,
        "content": content,
        "file": str(fpath),
        "encoding": encoding,
    }


def load_all_artifacts(artifact_dirs: dict, lab_dir: Path) -> dict:
    """Load all artifacts from all directories. Returns {id: artifact_dict}.

    This is the canonical loader used by all modules.
    Each artifact dict contains: id, type, title, status, severity, file,
    fpath, meta, body, full_content, created, updated, last_verified,
    confidence, source, tags, encoding.
    """
    artifacts = {}
    template_names = TEMPLATE_NAMES

    for atype, dirpath in artifact_dirs.items():
        if not dirpath.exists():
            continue
        for fpath in dirpath.glob("*.md"):
            if any(t in fpath.name.lower() for t in template_names):
                continue
            try:
                content, encoding = read_text_safe(fpath)
                meta, body = parse_frontmatter(content)
            except OSError:
                continue

            aid = meta.get("id", "")
            if not aid:
                m = ID_PATTERN.search(fpath.stem)
                if m:
                    aid = m.group(1)
            if not aid:
                continue

            fpath_rel = str(fpath.relative_to(lab_dir)) if fpath.is_relative_to(lab_dir) else str(fpath)

            artifacts[aid] = Artifact(
                id=aid,
                type=meta.get("type", atype),
                title=meta.get("title", fpath.stem),
                status=meta.get("status", "unknown"),
                severity=meta.get("severity", ""),
                file=fpath_rel,
                fpath=fpath,
                meta=meta,
                body=body,
                full_content=content,
                created=meta.get("created", ""),
                updated=meta.get("updated", ""),
                last_verified=meta.get("last_verified", ""),
                confidence=meta.get("confidence", ""),
                source=meta.get("source", ""),
                tags=meta.get("tags", []),
                encoding=encoding,
            )

    return artifacts
