# Архитектура artifact-pulse

## Обзор

artifact-pulse — система мониторинга здоровья артефактов и управления инсайтами лаборатории LabDoctorM.

Два контура:
- **Артефакты** — мониторинг ADR, паттернов, правил, инцидентов (health check, граф, старение)
- **Инсайты** — сбор, дедупликация, консолидация, семантический поиск

## Компоненты

### Контур артефактов

```
artifact_core.py          — Ядро: парсинг frontmatter, загрузка артефактов
artifact_types.py         — Artifact dataclass (каноническое представление)
artifact_health.py        — Health check (9 измерений, score 0-100)
artifact_graph.py         — Граф зависимостей (DOT/JSON/HTML)
artifact_aging.py         — Старение: active → stale → archived
artifact_provenance.py    — Происхождение, confidence decay
artifact_constraints.py   — Структурные ограничения, циклы
artifact_link_checker.py  — Проверка ссылок, orphans
artifact_stats.py         — Статистика, рейтинг
artifact_changelog.py     — Версионирование
artifact_monitor.py       — Тренды, алерты
search_artifacts.py       — Полнотекстовый поиск
normalize_frontmatter.py  — Валидация frontmatter
audit_report.py           — Комплексный аудит-отчёт
```

### Контур инсайтов

```
artifact_insights.py       — CRUD, status flow, semantic dedup, CLI
session_insights_miner.py — Извлечение инсайтов из сессий агентов
scripts/build_faiss_index.py — Построение FAISS индекса
scripts/migrate_to_sqlite.py — Миграция JSON → SQLite
```

## Хранение данных

### SQLite (`insights.db`)
- WAL mode для безопасной конкурентной записи
- Таблица `insights`: id, timestamp, content, type, source, status, confirmations, importance, tags, session_id, agent_pair, embedding
- Индексы: status, type, source

### FAISS (`insights.faiss`)
- IndexFlatIP (Inner Product = cosine similarity для normalized vectors)
- 235 векторов × 1024 dim
- Обновляется при добавлении новых инсайтов

### Ollama bge-m3-cpu
- Локальная embedding модель (CPU-only)
- Модель: bge-m3-cpu, num_ctx=2048, num_batch=256, num_thread=3
- API: `POST /api/embeddings`

## Status Flow инсайтов

```
new → verified → artifact
```

- **new** — только что добавлен
- **verified** — подтверждён ≥2 раза (confirmations >= 2)
- **artifact** — верифицирован + importance >= threshold + trusted source
- **rejected** — отклонён
- **archived** — архивирован

Команды:
- `verify --id INS-XXX` — increment confirmations, авто new→verified
- `promote --id INS-XXX` — verified→artifact
- `consolidate` — массовый переход по всем инсайтам

## Semantic Deduplication

1. Генерируем embedding нового текста через Ollama (~1 сек)
2. Ищем в FAISS (cosine similarity, <1ms)
3. Если cosine >= 0.85 → дубликат, пропускаем
4. Если cosine < 0.85 → новый, сохраняем
5. Fallback: точное совпадение по тексту (без Ollama)

## Тесты

```bash
python3 -m pytest tests/ -v
# 167 passed, 10 skipped
```

Покрытие:
- `test_insights.py` — 33 теста: CRUD, status flow, dedup, CLI, edge cases
- `test_session_miner.py` — security patterns, classification, integration
- `test_migration_flock.py` — миграция JSON ↔ SQLite, lock-файлы
- `test_artifact_system.py` — 108 тестов системы артефактов

## Зависимости

- Python 3.10+
- PyYAML >= 6.0
- faiss-cpu >= 1.7
- pytest >= 9.0
- Ollama (локальный, порт 11434)
