"""artifact_types.py — типы данных для системы артефактов LabDoctorM."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Artifact:
    """Каноническое представление артефакта.

    Поля соответствуют ключам из load_all_artifacts() для обратной совместимости.
    Доступ через атрибуты (art.id) или через словарь (art["id"]).
    """
    id: str
    type: str
    title: str
    status: str = "unknown"
    severity: str = ""
    file: str = ""
    fpath: Path = field(default_factory=Path)
    meta: dict = field(default_factory=dict)
    body: str = ""
    full_content: str = ""
    created: str = ""
    updated: str = ""
    last_verified: str = ""
    confidence: str = ""
    source: str = ""
    tags: list = field(default_factory=list)
    encoding: str = "utf-8"

    def __getitem__(self, key: str):
        """Обратная совместимость: доступ как к словарю."""
        return getattr(self, key)

    def get(self, key: str, default=None):
        """Обратная совместимость: dict.get()."""
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        """Обратная совместимость: 'key' in artifact."""
        return hasattr(self, key)

    def keys(self):
        """Обратная совместимость: итерация по ключам."""
        return self.__dataclass_fields__.keys()

    def values(self):
        """Обратная совместимость: итерация по значениям."""
        return (getattr(self, f) for f in self.__dataclass_fields__)

    def items(self):
        """Обратная совместимость: итерация по парам."""
        return ((f, getattr(self, f)) for f in self.__dataclass_fields__)
