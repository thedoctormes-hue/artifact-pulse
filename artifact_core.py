"""artifact_core.py — общие функции для всех модулей Artifact Pulse.

Содержит:
- parse_frontmatter() — парсинг YAML frontmatter из .md файлов
- load_artifact_file() — загрузка одного артефакта
- detect_encoding() / read_text_safe() — детекция кодировки
- ID_PATTERN, REF_PATTERN, TEMPLATE_NAMES — общие константы
"""

import re
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────

ID_PATTERN = re.compile(r"^([A-Z]{2,4}-\d{3,4})$")
REF_PATTERN = re.compile(r"\b([A-Z]{2,4}-\d{3,4})\b")
REF_PATTERN_LOOSE = re.compile(r"\b((?:PAT|ADR|RUL|BL|INS|INC|SPEC|MET)-[0-9]+)\b")

TEMPLATE_NAMES = {"template", "шаблон", "readme"}

# ── Frontmatter ────────────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns:
        (metadata_dict, body_string)

    Supports:
        - key: value
        - key: "quoted value"
        - key: 'quoted value'
        - key: [list, of, values]
    """
    if not content.startswith("---"):
        return {}, content

    end = content.find("---", 3)
    if end == -1:
        return {}, content

    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()

    metadata = _parse_yaml_block(fm_text)
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

    metadata = _parse_yaml_block(fm_text)
    return metadata, body, fm_text


def _parse_yaml_block(text: str) -> dict:
    """Parse a simple YAML block (frontmatter) into a dict.

    Supports:
        - key: value
        - key: "quoted value"
        - key: 'quoted value'
        - key: [inline, list]
        - key:\n  - item1\n  - item2   (multi-line list)
    """
    metadata = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in stripped:
            i += 1
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        # Multi-line list: key:\n  - item\n  - item
        if not value and i + 1 < len(lines) and lines[i + 1].strip().startswith("- "):
            items = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith("- "):
                item = lines[i].strip()[2:].strip().strip('"').strip("'")
                if item:
                    items.append(item)
                i += 1
            metadata[key] = items
            continue

        # Inline list: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            value = [v.strip().strip('"').strip("'") for v in value[1:-1].split(",") if v.strip()]

        metadata[key] = value
        i += 1

    return metadata


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
        dirpath = Path(dirpath) if isinstance(dirpath, str) else dirpath
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

            artifacts[aid] = {
                "id": aid,
                "type": meta.get("type", atype),
                "title": meta.get("title", fpath.stem),
                "status": meta.get("status", "unknown"),
                "severity": meta.get("severity", ""),
                "file": fpath_rel,
                "fpath": fpath,
                "meta": meta,
                "body": body,
                "full_content": content,
                "created": meta.get("created", ""),
                "updated": meta.get("updated", ""),
                "last_verified": meta.get("last_verified", ""),
                "confidence": meta.get("confidence", ""),
                "source": meta.get("source", ""),
                "tags": meta.get("tags", []),
                "encoding": encoding,
            }

    return artifacts
