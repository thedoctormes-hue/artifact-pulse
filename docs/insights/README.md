# Инсайты (Insights) — Система управления знаниями лаборатории

## Обзор

Система инсайтов artifact-pulse предназначена для:
- Сбора инсайтов из сессий агентов
- Семантической дедупликации (предотвращение дублирования знаний)
- Консолидации и верификации знаний
- Быстрого поиска по смыслу (не по ключевым словам)

## Архитектура

```
┌──────────────────────────────┐
│      Источники инсайтов       │
│  Сессии агентов  │  Ручной ввод  │
└─────────────┬─────────────────┘
              ▼
┌──────────────────────────────┐
│   session_insights_miner.py   │
│  - Извлечение из сессий       │
│  - Security pattern detection │
│  - Type classification        │
└─────────────┬─────────────────┘
              ▼
┌──────────────────────────────┐
│   artifact_insights.py        │
│  - CRUD операции              │
│  - Статус-флоу new→verified→artifact │
│  - Семантическая дедуп        │
│  - SQLite + FAISS хранение    │
└─────────────┬─────────────────┘
              ▼
┌──────────────────────────────┐
│         Хранилище             │
│  SQLite (insights.db)         │
│  FAISS index (insights.faiss) │
│  Ollama bge-m3-cpu            │
└──────────────────────────────┘
```

## Компоненты

### 1. `artifact_insights.py` — Ядро системы инсайтов

**Функции:**
- `add_insight()` — добавить новый инсайт с проверкой на дубликат
- `list_insights()` — получить список с фильтрацией
- `verify_insight()` — подтвердить инсайт (увеличить confirmations)
- `promote_insight()` — перевести verified → artifact
- `consolidate()` — массовый переход по статус-флоу
- `show_stats()` — статистика по статусам, типам, источникам

**Статус-флоу:**
```
new → (подтверждений >= 2) → verified → (importance >= threshold AND доверенный источник) → artifact
```

**Доверенные источники:** owl, dominika, antcat, sessions, manual, bestia, kotolizator, mangust, voron, shtreykbreher

### 2. `session_insights_miner.py` — Добытчик инсайтов

**Функции:**
- `extract_insights()` — извлечение потенциальных инсайтов из текста сессии
- `is_security_insight()` — обнаружение security-паттернов (vulnerability, leak, etc.)
- `classify_type()` — определение типа (finding, error, decision, pattern)
- `process_session()` — основная функция: обработать trajectory файл

### 3. `scripts/build_faiss_index.py` — Построение FAISS индекса

**Оптимизации:**
- Retry при HTTP 500 от Ollama
- Rate limiting (exponential backoff)
- FAISS IndexFlatIP для быстрого поиска по cosine similarity

### 4. `scripts/migrate_to_sqlite.py` — Миграция с дедупом

- Перенос из JSON в SQLite
- Семантическая дедупликация во время миграции
- Сохранение всех метаданных

## Хранение данных

### SQLite (`insights.db`)
- **Таблица:** insights
- **Поля:**
  - id (TEXT PRIMARY KEY) — формат INS-YYYYMMDDHHMMSS-XXXXXXXX
  - timestamp (TEXT) — ISO 8601 UTC
  - content (TEXT) — текст инсайта
  - type (TEXT) — finding/error/pattern/decision/anti-pattern/security/insight
  - source (TEXT) — источник (имя агента)
  - status (TEXT) — new/verified/artifact/rejected/archived
  - importance (REAL) — 0.3/0.6/0.9 (low/medium/high)
  - confirmations (INTEGER) — количество подтверждений
  - tags (TEXT) — CSV список тегов
  - session_id (TEXT) — ID сессии
  - agent_pair (TEXT) — пара агентов
  - embedding (BLOB) — 1024-dim вектор как массив float32
  - created_at/updated_at (TEXT) — автоматические timestamps

**Индексы:**
- idx_ins_status (status)
- idx_ins_type (type)
- idx_ins_source (source)

### FAISS (`insights.faiss`)
- **Тип:** IndexFlatIP (Inner Product)
- **Размерность:** 1024
- **Метрика:** Cosine similarity (после L2 нормализации)
- **Обновляется:** При каждом добавлении инсайта через `_get_embedding()`

## Как использовать

### CLI

```bash
# Добавить инсайт
python3 artifact_insights.py add \
  --content "Обнаружена SQL-инъекция в модуле авторизации" \
  --source "antcat" \
  --type "finding" \
  --confidence "high" \
  --context "security audit" \
  --tags "sql,injection,auth" \
  --session-id "sess-123" \
  --agent-pair "antcat-owl"

# Подтвердить инсайт
python3 artifact_insights.py verify --id INS-20260618103000-abcd1234

# Перевести в artifact
python3 artifact_insights.py promote --id INS-20260618103000-abcd1234

# Список новых инсайтов
python3 artifact_insights.py list --status new --limit 10

# Статистика
python3 artifact_insights.py stats

# Консолидация (запускать периодически)
python3 artifact_insights.py consolidate --min-confidence 0.6
```

### Из кода

```python
from artifact_insights import add_insight, verify_insight, promote_insight

insight = add_insight(
    content="New finding",
    source="myagent",
    insight_type="finding",
    confidence="high"
)

# Подтвердить
verify_insight(insight["id"])

# Перевести в artifact
promote_insight(insight["id"])
```

## Технологический стек

- **Python 3.10+**
- **SQLite** — WAL mode для безопасной конкурентной записи
- **FAISS-CPU** — быстрый векторный поиск (IndexFlatIP)
- **Ollama** — локальная embedding модель bge-m3-cpu
- **pytest** — фреймворк тестирования

## Тесты

```bash
python3 -m pytest tests/test_insights.py -v
python3 -m pytest tests/test_session_miner.py -v
python3 -m pytest tests/test_migration_flock.py -v
```

**Всего:** 167 passed, 10 skipped

## Размеры данных (на 18.06.2026)

- SQLite БД: ~1.2 MB
- FAISS индекс: 941 KB (235 векторов × 1024 × 4 bytes)
- В среднем на инсайт: ~5 KB

## Планы развития

1. **API-слой** (FastAPI) — эндпоинты для внешних систем
2. **Автоматический сбор** — интеграция с логами агентов через filewatcher
3. **Улучшенный поиск** — гибридный поиск (ключевые слова + семантика)
4. **Экспорт/импорт** — в JSON/CSV для бэкапа и миграции
5. **Визуализация** — дашборд статуса инсайтов

---
*Документация актуальна на 18.06.2026*