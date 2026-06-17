"""artifact_constants.py — единый источник констант для всех модулей Artifact Pulse.

Содержит:
- Паттерны для ID и ссылок (ID_PATTERN, REF_PATTERN, REF_PATTERN_LOOSE)
- Допустимые статусы по типам (VALID_STATUSES) и все вместе (ALL_VALID_STATUSES)
- Допустимые значения confidence (VALID_CONFIDENCE)
- Допустимые источники (VALID_SOURCES)
- Обязательные поля по типам (REQUIRED_FIELDS)
- Интервалы ревью (REVIEW_INTERVALS)
- Правила decay (CONFIDENCE_DECAY)
- Цвета и формы для графа (STATUS_COLORS, TYPE_SHAPES)
- Имена шаблонов (TEMPLATE_NAMES)
"""

import re
from typing import Final

# ── ID & Reference Patterns ───────────────────────────────────

ID_PATTERN: Final = re.compile(r"^([A-Z]{2,4}-\d{3,4})$")
# REF_PATTERN — only matches known artifact ID prefixes (not LLM-, KDL-, SHA-256, etc.)
REF_PATTERN: Final = re.compile(
    r"\b((?:PAT|ADR|RUL|BL|INS|INC|SPEC|MET|SYS|RPT)-\d{3,4})\b"
)
REF_PATTERN_LOOSE: Final = re.compile(
    r"\b((?:PAT|ADR|RUL|BL|INS|INC|SPEC|MET|SYS|RPT)-[0-9]+)\b"
)

# Match markdown links: [text](path)
MD_LINK_PATTERN: Final = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# Match wiki-style links: [[ART-001]]
WIKI_LINK_PATTERN: Final = re.compile(r"\[\[([A-Z]{2,4}-\d{3,4})\]\]")

# ── Valid Statuses by Type ────────────────────────────────────

VALID_STATUSES: Final[dict[str, set[str]]] = {
    "adr": {
        "proposed",
        "accepted",
        "rejected",
        "deprecated",
        "superseded",
        "archived",
        "active",
        "draft",
    },
    "pattern": {"draft", "active", "deprecated", "archived", "accepted", "proposed"},
    "rule": {
        "draft",
        "active",
        "deprecated",
        "archived",
        "pending",
        "accepted",
        "proposed",
    },
    "backlog": {
        "pending",
        "in_progress",
        "done",
        "cancelled",
        "archived",
        "active",
        "open",
        "closed",
        "resolved",
        "accepted",
        "proposed",
    },
    "incident": {
        "open",
        "investigating",
        "resolved",
        "closed",
        "archived",
        "pending",
        "active",
        "mitigated",
    },
    "sys": {"draft", "active", "archived", "deprecated", "accepted", "proposed"},
    "report": {"draft", "final", "archived", "accepted", "active", "pending"},
    "metric": {"active", "deprecated", "archived", "draft", "pending", "accepted"},
}

# All known valid statuses (union of all sets)
ALL_VALID_STATUSES: Final[set[str]] = set().union(*VALID_STATUSES.values())

# ── Confidence & Source ───────────────────────────────────────

VALID_CONFIDENCE: Final[set[str]] = {"high", "medium", "low", "outdated"}
VALID_SOURCES: Final[set[str]] = {
    "manual",
    "agent",
    "owl_agent",
    "evolve_orchestrator",
    "insight",
    "import",
    "unknown",
}

# Confidence decay rules: (days_without_verification, new_confidence)
CONFIDENCE_DECAY: Final[list[tuple[float, str]]] = [
    (30, "high"),
    (60, "medium"),
    (90, "low"),
    (float("inf"), "outdated"),
]

# ── Required Fields by Type ───────────────────────────────────

REQUIRED_FIELDS: Final[dict[str, list[str]]] = {
    "pattern": ["id", "type", "title", "status", "created"],
    "adr": ["id", "type", "title", "status", "created"],
    "rule": ["id", "type", "title", "status", "created"],
    "spec": ["id", "type", "title", "status", "created"],
    "incident": ["id", "type", "title", "status", "created"],
    "metric": ["id", "type", "title", "status", "created"],
}

# ── Review Intervals by Type (days) ───────────────────────────

REVIEW_INTERVALS: Final[dict[str, int]] = {
    "pattern": 90,
    "adr": 180,
    "rule": 90,
    "spec": 60,
    "incident": 30,
    "metric": 30,
}

# ── Graph Visualization ───────────────────────────────────────

STATUS_COLORS: Final[dict[str, str]] = {
    "active": "#4CAF50",
    "accepted": "#2196F3",
    "proposed": "#FF9800",
    "draft": "#9E9E9E",
    "pending": "#9E9E9E",
    "archived": "#795548",
    "rejected": "#F44336",
    "deprecated": "#F44336",
    "stale": "#FF5722",
    "consolidated": "#00BCD4",
    "new": "#CDDC39",
    "unknown": "#9E9E9E",
}

TYPE_SHAPES: Final[dict[str, str]] = {
    "pattern": "box",
    "adr": "ellipse",
    "rule": "diamond",
    "spec": "note",
    "incident": "octagon",
    "metric": "hexagon",
    "backlog": "folder",
}

# ── Template Filtering ────────────────────────────────────────

TEMPLATE_NAMES: Final[set[str]] = {"template", "шаблон", "readme"}

# ── Type Prefix Map ───────────────────────────────────────────

TYPE_PREFIX: Final[dict[str, str]] = {
    "adr": "ADR",
    "pattern": "PAT",
    "rule": "RUL",
    "backlog": "BL",
    "incident": "INC",
    "sys": "SYS",
    "report": "RPT",
    "metric": "MET",
}

# ── Alert Thresholds ──────────────────────────────────────────

ALERT_WARN_SCORE: Final[int] = 70
ALERT_CRIT_SCORE: Final[int] = 50
ALERT_BROKEN_LINKS: Final[int] = 5
ALERT_ORPHANS: Final[int] = 10
ALERT_OUTDATED_PCT: Final[int] = 30

# ── History Rotation ──────────────────────────────────────────

HISTORY_MAX_ENTRIES: Final[int] = 1000
HISTORY_MAX_DAYS: Final[int] = 90

# ── Aging Defaults ────────────────────────────────────────────

DEFAULT_STALE_DAYS: Final[int] = 90
DEFAULT_ARCHIVE_DAYS: Final[int] = 180
