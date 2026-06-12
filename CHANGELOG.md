# Changelog

Все значимые изменения в проекте artifact-pulse документируются здесь.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).

## [4.2.0] - 2026-06-22

### Added
- `Artifact` dataclass (`artifact_types.py`) — каноническое представление артефакта с dict-совместимостью (`__getitem__`, `get`, `__contains__`, `keys`, `values`, `items`)

### Changed
- `artifact_aging.py` — адаптер `load_all_artifacts()` убран, модуль работает с `Artifact` напрямую через `art.body`, `art.fpath`, `art.get()`
- `artifact_stats.py` — адаптер убран, `meta.get("_type")` → `art.type`, `meta.get("_body")` → `art.body`, `meta.get("_file")` → `art.file`
- `search_artifacts.py` — `load_artifacts()` возвращает `list(raw.values())`, `artifact.body` вместо `artifact.get("_body")`
- `README.md` — обновлён до v4.2.0, 108 тестов, описание Artifact dataclass
- `pyproject.toml` — версия 4.2.0

### Removed
- Промежуточные адаптеры с `_`-полями (`_body`, `_fpath`, `_file`, `_type`) из `artifact_aging.py`, `artifact_stats.py`, `search_artifacts.py`
- Локальные переопределения `load_all_artifacts()` в указанных модулях (теперь все используют канонический из `artifact_core.py`)

### Fixed
- `count_inbound_links()` и `get_inbound_sources()` — поддержка и `Artifact` и обычных dict через `hasattr` fallback (совместимость с тестами)

## [4.1.0] - 2026-06-22

### Added
- Ротация `health_history.jsonl` — автоочистка записей старше 90 дней и сверх 1000 записей (`artifact_monitor.py`)
- CLI-флаг `--rotate` для принудительной ротации истории
- `_dir_fingerprint()` в `search_artifacts.py` — O(directories) stale detection вместо O(n) stat()
- `_needs_quoting()` в `artifact_changelog.py` — определение строк требующих кавычек в YAML
- `VALID_STATUSES` и `ALL_VALID_STATUSES` в `artifact_core.py` — единый source of truth для всех модулей
- 16 новых тестов: `TestHistoryRotation`, `TestDirFingerprint`, `TestNeedsQuoting`, `TestDaysSinceEdgeCases`
- `CHANGELOG.md`, `docs/ADR/`, `docs/ARCHITECTURE.md` — документация по стандартам лаборатории

### Changed
- `rebuild_frontmatter()` генерирует block-style YAML для всех list (предотвращает type coercion)
- `days_since()` принимает `datetime` объекты напрямую, не только строки
- `load_index()` использует агрегированный mtime директорий вместо перебора всех файлов
- `VALID_STATUSES` консолидирован в `artifact_core.py`, все модули импортируют оттуда
- `README.md` переписан: убран несуществующий `src/`, добавлена реальная структура, таблица типов/статусов
- `pyproject.toml` дополнен `[build-system]` и `[tool.setuptools.packages.find]`

### Fixed
- `rebuild_frontmatter()` — type coercion при inline list с history entries (дата:текст → datetime.date key)
- `days_since()` — возвращал 9999 для `datetime` объектов из-за `fromisoformat` на не-строке
- `test_last_verified_not_future` — TypeError при сравнении datetime объектов
- `VALID_STATUSES` — не соответствовал реальным статусам в разных модулях
- `pip install -e .` — не работал из-за отсутствия `[build-system]`

## [4.0.0] - 2026-06-04

### Added
- Полная система мониторинга здоровья артефактов (9 измерений, score 0-100)
- Health check: frontmatter, links, aging, duplicates, code_refs, provenance, constraints, insights, infrastructure
- Граф зависимостей (DOT/JSON/HTML с D3.js)
- Полнотекстовый поиск с persistent index
- Система старения: active → stale (90d) → archived (180d)
- Confidence decay: high → medium → low → outdated
- Мониторинг трендов и алертов (JSONL history)
- Нормализация frontmatter
- Структурные ограничения (циклы, противоречия)
- 68 unit-тестов
- 11 entry points (CLI)
- Systemd unit-файлы для таймеров
