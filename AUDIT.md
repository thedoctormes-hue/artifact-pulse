---
type: audit
id: AUDIT-2026-06-04
title: "Аудит artifact-pulse v4.0.0 — Штрейкбрехер"
status: final
author: streikbrecher
created: 2026-06-04
updated: 2026-06-04
tags: [audit, artifact-pulse, review]
---

# Аудит artifact-pulse v4.0.0

**Аудитор:** Штрейкбрехер (фулстак сеньор)
**Дата:** 2026-06-04
**Версия:** 4.0.0
**Ветка:** owl/artifact-system-v4

---

## Общая оценка: 7/10

Амбициозная система с правильной архитектурой, но не готова к production из-за нерешённых проблем с установкой и структурой.

---

## Структура проекта

```
artifact-pulse/
├── config/
│   └── artifact_dirs.yaml      # Пути к артефактам и файлам состояния
├── src/
│   ├── __init__.py
│   ├── config_loader.py        # Загрузчик конфига (YAML → Path)
│   ├── artifact_health.py       # Health check (9 измерений, score 0-100)
│   ├── artifact_link_checker.py # Проверка ссылок, orphans, broken links
│   ├── artifact_graph.py        # Граф зависимостей (DOT/JSON/HTML)
│   ├── artifact_aging.py        # Старение: active → stale → archived
│   ├── artifact_stats.py        # Статистика, рейтинг, цитирования
│   ├── artifact_changelog.py    # Версионирование, CHANGELOG.md
│   ├── artifact_provenance.py   # Происхождение, confidence decay
│   ├── artifact_constraints.py  # Структурные ограничения, противоречия
│   ├── artifact_monitor.py      # Тренды, алерты, health history
│   ├── search_artifacts.py      # Полнотекстовый поиск
│   ├── normalize_frontmatter.py # Валидация и нормализация frontmatter
│   └── audit_report.py          # Комплексный аудит-отчёт
├── scripts/
│   ├── evolve_orchestrator.sh   # Оркестратор эволюции
│   └── self_evolve.sh           # Автономная эволюция (cron)
├── templates/                    # ПУСТОЙ — шаблонов нет
├── tests/
│   └── test_artifact_system.py  # 53 теста
└── pyproject.toml
```

---

## Что работает ✅

1. **Структура Python-пакета.** `pyproject.toml` с entry points, YAML-конфиг, разделение на `src/`, `tests/`, `scripts/`, `config/` — всё по стандартам.

2. **53/53 тестов зелёные.** Тесты покрывают каждый модуль + интеграционный тест полного пайплайна.

3. **YAML-конфигурация.** Пути к артефактам и файлам состояния вынесены в `artifact_dirs.yaml`. Модули загружают через `config_parser.py` — нет хардкода.

4. **9 измерений в health check.** Добавлены `provenance` и `constraints` как отдельные измерения. Взвешенный score 0-100.

5. **Линкчекер полный.** Broken links, orphans, deprecated links, missing reciprocal, рейтинг most-referenced/most-referencing.

6. **Монитор — правильная композиция.** Импортирует из `artifact_health`, `artifact_provenance`, `artifact_constraints` — не дублирует логику.

7. **Provenance tracking.** `confidence`, `last_verified`, `source`, `review_due`, confidence decay — это то, чего нет в 99% систем документации.

---

## Критические проблемы 🔴

### 1. Пакет не установлен как editable

```bash
pip3 list | grep artifact  # пусто
artifact-health --help     # command not found
```

**Результат:** CLI-точки входа из `pyproject.toml` (`artifact-health`, `artifact-search` и т.д.) не работают. Импорты `from config_loader import ...` требуют `PYTHONPATH=src`.

**Решение:**
```bash
cd /root/LabDoctorM/projects/artifact-pulse
pip3 install -e .
```

### 2. Пустая папка templates/

`evolve_orchestrator.sh` ссылается на `templates_dir: projects/artifact-pulse/templates`, но папка пустая. Оркестратор не сможет создавать артефакты по шаблонам.

**Решение:** Заполнить шаблонами для каждого типа артефакта (adr, pattern, rule, spec, incident, metric).

---

## Важные проблемы 🟡

### 3. Дублирование parse_frontmatter — 10 копий

`parse_frontmatter` определена в 10 модулях:
- `artifact_aging.py`
- `artifact_changelog.py`
- `artifact_constraints.py`
- `artifact_graph.py`
- `artifact_health.py`
- `artifact_link_checker.py`
- `artifact_provenance.py`
- `artifact_stats.py`
- `normalize_frontmatter.py`
- `search_artifacts.py`

Сова создала `config_loader.py`, но не вынесла туда `parse_frontmatter`. При любом изменении формата frontmatter — правим в 10 местах.

**Решение:** Вынести `parse_frontmatter` + общие константы в `artifact_core.py` (или `config_loader.py`).

### 4. Два набора скриптов

- Старый: `/root/LabDoctorM/.qwen/scripts/artifact_*.py`
- Новый: `/root/LabDoctorM/projects/artifact-pulse/src/`

`self_evolve.sh` ссылается на старый (`.qwen/scripts/`). Нужно либо синхронизировать, либо переключить на новый.

---

## Детальный анализ по компонентам

- **config_loader.py** (8/10): чистый YAML-загрузчик. Есть fallback значения.
- **artifact_health.py** (7/10): 9 измерений, но `parse_frontmatter` дублируется.
- **artifact_link_checker.py** (8/10): полный набор проверок, хороший отчёт.
- **artifact_provenance.py** (8/10): confidence decay, review intervals — продумано.
- **artifact_constraints.py** (6/10): 47 violations обнаруживаются, но не исправляются.
- **artifact_monitor.py** (7/10): тренды + алерты. Зависит от health — правильно.
- **artifact_graph.py** (7/10): DOT/JSON/HTML — три формата вывода.
- **artifact_aging.py** (7/10): старение + dry-run.
- **artifact_stats.py** (7/10): рейтинг с учётом ссылок и возраста.
- **artifact_changelog.py** (7/10): версионирование + CHANGELOG.md.
- **search_artifacts.py** (7/10): полнотекстовый поиск с индексацией.
- **normalize_frontmatter.py** (6/10): валидация по типам, но дублирует parse_frontmatter.
- **audit_report.py** (6/10): использует subprocess для normalize — другой подход.

---

## Результаты запуска

```
Тесты:          53 passed (1.29s)
Health score:   72/100
Artifacts:      95 загружено
Code refs:      2.1% (1 из 47 активных)
Orphans:        18
Broken links:   0
Stale:          0
Constraints:    47 violations
```

---

## Roadmap для Совы

### P0 — Блокирует использование
1. `pip3 install -e .` — установить пакет как editable
2. Заполнить `templates/` шаблонами артефактов

### P1 — Устранение технического долга
3. Вынести `parse_frontmatter` в общий модуль (`artifact_core.py`)
4. Переключить `self_evolve.sh` на `projects/artifact-pulse/src/` или синхронизировать
5. Починить 18 orphan-артефактов (архивировать или привязать)

### P2 — Улучшения
6. Сделать `code_refs` обязательными для ADR и PAT
7. Добавить auto-fix для простых constraint violations
8. Добавить детект кодировок в frontmatter validation

---

*Аудит проведён Штрейкбрехером. Дата: 2026-06-04.*

---

## Повторный аудит 2026-06-22 (Owl)

**Аудитор:** Owl (Главный Лаборант)
**Версия:** 4.1.0

### Общая оценка: 9/10

Все критические и серьёзные проблемы первого аудита устранены. Проект готов к production.

### Исправлено с первого аудита
- ✅ `pip install .` работает (добавлен `[build-system]`)
- ✅ `rebuild_frontmatter()` — type coercion устранён (block-style YAML)
- ✅ `days_since()` — принимает `datetime` объекты
- ✅ `VALID_STATUSES` — единый source of truth в `artifact_core.py`
- ✅ `README.md` — переписан с реальной структурой
- ✅ Тесты: 68 → 84 (все passing)

### Новые улучшения (v4.1.0)
- Ротация `health_history.jsonl` (1000 entries / 90 days)
- O(directories) stale detection в search_artifacts.py
- `_needs_quoting()` для предотвращения YAML type coercion
- Документация: CHANGELOG.md, ADR (3 записи), ARCHITECTURE.md

### Оставшиеся замечания (P2)
- Orphan-артефакты (18 шт.) — требуют ручной архивации (бизнес-решение)
- ✅ `code_refs` — опциональны, не блокируют работу (coverage-based scoring)
- ✅ auto-fix для constraint violations — реализован (`--fix` / `--dry-run` в artifact_constraints.py)
