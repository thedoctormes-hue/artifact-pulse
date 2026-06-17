# Архитектура artifact-pulse

## Обзор

Artifact Pulse — система мониторинга здоровья артефактов LabDoctorM. Оперирует markdown-файлами с YAML frontmatter, вычисляет health score (0-100), отслеживает тренды, генерирует алерты.

## Стек

- **Python 3.10+**
- **PyYAML >= 6.0** — парсинг frontmatter
- **pytest >= 7.0** — тестирование (dev)
- **ruff >= 0.4.0** — линтинг (dev)
- **mypy >= 1.0** — тайпчекинг (dev)

## Entry Points (15)

| Команда | Модуль | Назначение |
|---------|--------|-----------|
| `artifact-health` | `artifact_health.py` | 9-мерный health check (0-100) |
| `artifact-search` | `search_artifacts.py` | Полнотекстовый поиск с индексом |
| `artifact-links` | `artifact_link_checker.py` | Битые ссылки, orphan-артефакты |
| `artifact-aging` | `artifact_aging.py` | Старение (active→stale→archived) |
| `artifact-stats` | `artifact_stats.py` | Ранжирование по цитированию |
| `artifact-monitor` | `artifact_monitor.py` | Тренды, алерты, история (JSONL) |
| `artifact-provenance` | `artifact_provenance.py` | Confidence decay, review due dates |
| `artifact-constraints` | `artifact_constraints.py` | Структурные constraints, циклы |
| `artifact-graph` | `artifact_graph.py` | DOT/JSON/D3.js визуализация |
| `artifact-changelog` | `artifact_changelog.py` | Генерация CHANGELOG.md |
| `artifact-audit` | `audit_report.py` | Комплексный аудит |
| `artifact-normalize` | `normalize_frontmatter.py` | Валидация + автофикс frontmatter |
| `artifact-dashboard` | `artifact_dashboard.py` | HTML дашборд с D3.js графом |
| `artifact-diff` | `artifact_diff.py` | Сравнение двух артефактов |
| `artifact-watch` | `artifact_watch.py` | Планировщик health check |
| `artifact-new` | `artifact_new.py` | Генератор шаблонов артефактов |

## Компоненты

```
┌──────────────────────────────────────────────────────────────┐
│ CLI Entry Points (15) │
│ health search links aging stats monitor provenance ... │
│ constraints graph changelog audit normalize dashboard │
│ diff watch new │
└───────────────────────────┬──────────────────────────────────┘
 │
┌───────────────────────────▼──────────────────────────────────┐
│ artifact_core.py │
│ parse_frontmatter() load_all_artifacts() │
│ validate_frontmatter() ← единая валидация (health/normalize)│
│ detect_encoding() read_text_safe() │
└───────────────────────────┬──────────────────────────────────┘
 │
 ┌──────────────────────┼──────────────────────┐
 │ │ │
┌────▼───────────┐ ┌───────▼──────────┐ ┌───────▼──────────┐
│ Health Check │ │ Aging │ │ Provenance │
│ (9 измерений) │ │ │ │ │
│ frontmatter │ │ active→stale │ │ confidence decay │
│ links │ │ →archived │ │ last_verified │
│ aging │ │ days_since() │ │ review_due │
│ duplicates │ │ count_inbound │ │ verify_artifact()│
│ code_refs │ │ _links() │ │ │
│ provenance │ │ analyze_cascade()│ │ │
│ constraints │ │ │ │ │
│ insights │ │ │ │ │
│ infrastructure │ │ │ │ │
└────────────────┘ └──────────────────┘ └──────────────────┘

┌────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Search │ │ Monitor │ │ Graph │
│ │ │ │ │ │
│ build_index() │ │ save_snapshot() │ │ DOT / JSON / │
│ load_index() │ │ load_history() │ │ HTML (D3.js) │
│ _dir_finger- │ │ compute_trends() │ │ force-directed │
│ print() │ │ check_alerts() │ │ simulation │
│ score_*() │ │ │ │ │
└────────────────┘ └──────────────────┘ └──────────────────┘

┌────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Diff │ │ Watch │ │ New │
│ │ │ │ │ │
│ frontmatter │ │ --once (timer) │ │ auto-ID │
│ outbound refs │ │ --interval N │ │ frontmatter │
│ inbound refs │ │ alerts-only │ │ yaml template │
│ body diff │ │ │ │ --dry-run │
└────────────────┘ └──────────────────┘ └──────────────────┘

┌────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Normalize │ │ Stats │ │ Dashboard │
│ │ │ │ │ │
│ validate_fm() │ │ citations │ │ HTML + D3.js │
│ fix_frontmatter│ │ rankings │ │ health score │
│ scan() │ │ composite_score │ │ distributions │
│ │ │ │ │ attention list │
└────────────────┘ └──────────────────┘ └──────────────────┘
```

## Единая валидация frontmatter

`validate_frontmatter()` в `artifact_core.py` — единая точка валидации для всех модулей:
- `artifact_health.check_frontmatter()` — проверяет артефакты + title quality + date format
- `artifact_new.generate_artifact()` — генерирует с валидным frontmatter
- Ранее дублировалась в normalize_frontmatter.py и audit_report.py — устранено

## Поток данных

### Health Check (9 измерений)
1. `load_all_artifacts()` → парсит все .md из `config/artifact_dirs.yaml`
2. Каждое измерение проверяет свою область (frontmatter, links, aging, duplicates, code_refs, provenance, constraints, insights, infrastructure)
3. `compute_overall_score()` → взвешенный score 0-100
4. `save_snapshot()` → запись в `health_history.jsonl` + ротация

### Monitoring
1. `run_health_snapshot()` — единый вызов для всех 9 измерений (включая provenance и constraints)
2. `compute_trends()` → velocity, direction (improving/degrading/stable)
3. `check_alerts()` → пороговые алерты (score < 50 CRITICAL, < 70 WARNING)

### Aging Lifecycle
```
active ──(>90d, 0 inbound)──→ stale ──(>180d)──→ archived
deprecated ──(>180d)──→ archived
draft ──(>180d)──→ archived
```
Артефакты с >= 2 inbound links никогда не стареют.

### Confidence Decay
```
(0-30d) → high
(30-60d) → medium
(60-90d) → low
(90d+) → outdated
```

## Конфигурация

Все пути задаются в `config/artifact_dirs.yaml`:
- `lab_dir` — корень лаборатории
- `artifact_dirs` — словарь тип → относительный путь
- `state_files` — пути к файлам состояния

## Файлы состояния

| Файл | Назначение | Ротация |
|------|-----------|---------|
| `health_history.jsonl` | История health checks | 1000 entries / 90 days |
| `search_index.json` | Поисковый индекс | При изменении файлов |
| `alerts.json` | Последние алерты | Перезапись |
| `trends.json` | Последние тренды | Перезапись |
| `artifact_stats.json` | Статистика (цитирование) | Перезапись |

## Тестирование

- **124 теста** в `tests/` (108 существующих + 16 новых)
- `pytest tests/ -v`

## Ключевые константы

Все константы в `artifact_constants.py` — ID паттерны, valid statuses by type, confidence decay rules, review intervals, alert thresholds (WARN=70, CRIT=50), aging thresholds (STALE=90d, ARCHIVE=180d), graph colors/shapes.

## Запуск

```bash
# Установка
pip install -e ".[dev]"

# Health check
artifact-health

# Сравнение артефактов
artifact-diff ADR-001 ADR-002

# Health check по расписанию (systemd timer)
artifact-watch --once

# Создать новый артефакт
artifact-new --type pattern --title "Описание паттерна"

# HTML дашборд
artifact-dashboard --output dashboard.html
```
