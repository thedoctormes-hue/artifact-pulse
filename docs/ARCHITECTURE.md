# Архитектура artifact-pulse

## Обзор

Artifact Pulse — система мониторинга здоровья артефактов LabDoctorM. Оперирует markdown-файлами с YAML frontmatter, вычисляет health score (0-100), отслеживает тренды, генерирует алерты.

## Стек

- **Python 3.10+**
- **PyYAML >= 6.0** — парсинг frontmatter
- **Jinja2** — шаблоны для HTML-графа (опционально)
- **pytest** — тестирование

## Компоненты

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Entry Points                      │
│  artifact-health  artifact-search  artifact-monitor ... │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                   artifact_core.py                      │
│  parse_frontmatter()  load_all_artifacts()             │
│  VALID_STATUSES (единый source of truth)              │
└────────────────────────┬────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼──────┐  ┌──────▼───────┐  ┌────▼──────────┐
│   Health     │  │    Search    │  │   Monitor     │
│   Check      │  │    Index     │  │   & Alerts   │
│              │  │              │  │               │
│ frontmatter  │  │ build_index()│  │ save_snapshot │
│ links        │  │ load_index() │  │ load_history  │
│ aging        │  │ _dir_finger- │  │ _rotate_hist  │
│ duplicates   │  │   print()    │  │ compute_trends│
│ code_refs    │  │ score_*()    │  │ check_alerts  │
│ provenance   │  └──────────────┘  └───────────────┘
│ constraints  │
│ insights     │  ┌──────────────┐  ┌───────────────┐
│ infrastruc.  │  │   Graph      │  │   Changelog   │
└──────────────┘  │   (DOT/      │  │               │
                  │   JSON/HTML) │  │ rebuild_front │
┌──────────────┐  └──────────────┘  │ _needs_quot  │
│   Aging      │                    │ add_history  │
│              │  ┌──────────────┐  └───────────────┘
│ days_since() │  │  Normalize   │
│ active→stale │  │  Frontmatter │  ┌───────────────┐
│ →archived    │  │              │  │   Provenance  │
└──────────────┘  │ VALID_STATUS │  │               │
                  │  (imported)  │  │ confidence    │
┌──────────────┐  └──────────────┘  │ decay         │
│   Stats      │                    │ last_verified │
│              │  ┌──────────────┐  └───────────────┘
│ citations    │  │ Constraints   │
│ rankings     │  │               │  ┌───────────────┐
└──────────────┘  │ cycles        │  │  Link Checker │
                  │ contradictions│  │               │
                  └──────────────┘  │ broken links  │
                                    │ orphans       │
                                    └───────────────┘
```

## Поток данных

### Health Check
1. `load_all_artifacts()` → парсит все .md файлы из `config/artifact_dirs.yaml`
2. Каждый модуль проверяет свою область (frontmatter, links, aging, ...)
3. `compute_overall_score()` → взвешенный score 0-100
4. `save_snapshot()` → запись в `health_history.jsonl` + ротация

### Search
1. `_dir_fingerprint()` → (max_mtime, file_count) по всем директориям
2. Если fingerprint изменился → `build_index()` → токенизация + сохранение
3. `score_index_entry()` → ранжирование по релевантности (title ×10, tags ×8, body ×3, id ×50)

### Monitoring
1. `save_snapshot()` → append + `_rotate_history()` (max 1000 entries, 90 days)
2. `load_history()` → чтение за период
3. `compute_trends()` → velocity, direction (improving/degrading/stable)
4. `check_alerts()` → пороговые алерты (score < 50 CRITICAL, < 70 WARNING)

## Конфигурация

Все пути задаются в `config/artifact_dirs.yaml`:
- `lab_dir` — корень лаборатории
- `artifact_dirs` — словарь тип → относительный путь
- `state_files` — пути к файлам состояния (history, index, alerts, trends)

## Файлы состояния

| Файл | Назначение | Ротация |
|------|-----------|---------|
| `health_history.jsonl` | История health checks | 1000 entries / 90 days |
| `search_index.json` | Поисковый индекс | При изменении файлов |
| `alerts.json` | Последние алерты | Перезапись |
| `trends.json` | Последние тренды | Перезапись |
