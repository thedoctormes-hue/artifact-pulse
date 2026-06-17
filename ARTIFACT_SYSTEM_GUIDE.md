# 🦉 Руководство по системе артефактов LabDoctorM

**Для каждого лаборанта.** Читай один раз — потом только команду из шпаргалки.

---

## Что это такое

**Артефакты** — единицы знаний лаборатории. Не код, не конфиги, а **решения, правила, инциденты, паттерны**.

**Artifact Pulse** — система, которая следит за здоровьем этих знаний: чтобы ссылки не рвались, артефакты не старели, правила не противоречили друг другу.

---

## Типы артефактов

| Тип | Папка | Что хранит | Пример |
|-----|-------|------------|--------|
| **ADR** | `adr/` | Архитектурные решения | `ADR-015-llm-openrouter-stack.md` |
| **PAT** | `patterns/` | Паттерны проектирования | `PAT-001-description-sistematiza.md` |
| **RUL** | `rules/` | Правила и политики | `RUL-001-no-tokens-in-git.md` |
| **BL** | `specs/` | Спецификации и бэклог | `BL-019-mission-statement.md` |
| **INC** | `incidents/` | Инциденты | `INC-001-twa-timing-attack.md` |
| **MET** | `metrics/` | Метрики | `MET-001-uptime-target.md` |

---

## Структура артефакта

Каждый артефакт — это `.md` файл с **YAML frontmatter**:

```markdown
---
id: ADR-015
type: adr
title: "Стек LLM моделей через OpenRouter"
status: active
created: 2026-05-20
updated: 2026-06-01
last_verified: 2026-06-01
confidence: high
source: manual
severity: medium
tags: [llm, openrouter, architecture]
---

# Заголовок

Содержание артефакта...
```

### Обязательные поля

- `id` — уникальный идентификатор (PAT-001, ADR-015, BL-043)
- `type` — тип артефакта (pattern, adr, rule, spec, incident, metric)
- `title` — заголовок
- `status` — active | stale | archived | deprecated
- `created` — дата создания (YYYY-MM-DD)

### Рекомендуемые поля

- `updated` — дата последнего обновления
- `last_verified` — дата последней верификации
- `confidence` — high | medium | low | outdated
- `source` — manual | agent | evolve_orchestrator | insight | import
- `severity` — critical | high | medium | low (для инцидентов)
- `tags` — список тегов

---

## Как создавать артефакт

### 1. Вручную

```bash
# Создать файл по шаблону
cp projects/artifact-pulse/templates/adr-template.md adr/ADR-021-my-decision.md

# Отредактировать frontmatter и содержимое
vim adr/ADR-021-my-decision.md
```

### 2. Через evolve_orchestrator

Инсайт → подтверждение → автоматическое создание артефакта:

```bash
# Добавить инсайт в очередь
echo '{"content": "...", "type": "adr"}' >> .qwen/artifacts/insights_queue.json

# Оркестратор обработает при следующе запуске (каждые 3ч)
```

### 3. Через self_evolve

Автоматическая эволюция существующих артефактов (каждые 6ч).

---

## Как ссылаться на артефакты

В любом `.md` файле лаборатории:

```markdown
Как описано в ADR-015, стек LLM использует OpenRouter.
См. также PAT-001 для паттерна систематизации.
```

**Правила:**
- Формат: `XXX-NNN` (PAT-001, ADR-015, BL-043)
- Не ссылайся на несуществующие артефакты — link checker найдёт
- Не ссылайся на архивированные из активных — это warning

---

## Автоматические проверки (systemd таймеры)

| Таймер | Частота | Что проверяет |
|--------|---------|---------------|
| `artifact-health` | 6ч | Общий health score (0-100), 9 измерений |
| `artifact-links` | 12ч | Целостность ссылок, orphans, broken links |
| `artifact-monitor` | 3ч | Тренды, алерты, деградация |
| `artifact-aging` | 24ч | Старение: active → stale → archived |
| `artifact-stats` | 12ч | Статистика, рейтинг, цитирования |
| `artifact-provenance` | 24ч | Confidence decay, верификация |
| `artifact-constraints` | 6ч | Структурные ограничения, противоречия |
| `search-rebuild` | 6ч | Пересборка поискового индекса |
| `artifact-audit` | 6ч | Комплексный аудит-отчёт |

---

## Команды (шпаргалка)

```bash
# Health check
cd projects/artifact-pulse && python3 src/artifact_health.py --verbose

# Поиск по артефактам
python3 src/search_artifacts.py "VPN" --limit 5

# Проверка ссылок
python3 src/artifact_link_checker.py

# Старение (dry-run)
python3 src/artifact_aging.py --dry-run

# Мониторинг + алерты
python3 src/artifact_monitor.py --check

# Статистика
python3 src/artifact_stats.py --update

# Верификация
python3 src/artifact_provenance.py --refresh

# Ограничения
python3 src/artifact_constraints.py

# Пересборка индекса
python3 -c "from src.search_artifacts import build_index; build_index()"

# Валидация frontmatter
python3 src/normalize_frontmatter.py --check

# Аудит-отчёт
python3 src/audit_report.py

# Граф зависимостей
python3 src/artifact_graph.py --format html --output /tmp/graph.html

# Тесты
python3 -m pytest tests/ -v
```

---

## Статусы артефактов

```
active → stale → archived
 ↓
 deprecated → archived
```

- **active** — актуален, используется
- **stale** — не обновлялся >90 дней, нет inbound links
- **deprecated** — заменён другим артефактом
- **archived** — историческая ценность, не активен

---

## Health Score — что значит

| Score | Статус | Что делать |
|-------|--------|------------|
| 90-100 | 🟢 Отлично | Продолжать поддерживать |
| 70-89 | 🟡 Хорошо | Исправить мелкие проблемы |
| 50-69 | 🟠 Требует внимания | Нужен аудит |
| 0-49 | 🔴 Критично | Немедленное вмешательство |

**Текущий score: 90/100** (на 04.06.2026)

---

## К кому обращаться

- **Сова** 🦉 — архитектура системы артефактов, аудит, стандарты
- **Кот** 🐱 — мониторинг, инфраструктура, VPN
- **ЗавЛаб** — стратегические решения по артефактам

---

## Важно помнить

1. **Артефакт без ссылок — мусор.** Если на артефакт никто не ссылается, он скорее всего не нужен.
2. **Артефакт без обновления умирает.** >90 дней без обновления → stale.
3. **Ссылки должны работать.** Broken link = потерянное знание.
4. **Не дублируй.** Два артефакта с одинаковым заголовком = путаница.
5. **Frontmatter — это контракт.** Без него артефакт не индексируется.

---

---

## Insight Catcher Pipeline — Автоматический ловец инсайтов

### Что это

Pipeline для автоматического сбора инсайтов из работы агентов и их превращения в артефакты. Заменяет бывшие Qwen PostToolUse hooks.

### Как работает цикл

```
Агент обнаруживает инсайт (ошибка, решение, находка, паттерн)
  → Вызывает: python3 artifact_insights.py add --content "..." --source "agent" --type "finding"
  → Инсайт записывается в .qwen/artifacts/insights_queue.json
  → Cron каждые 60 мин: python3 artifact_insights.py consolidate
  → Связанные инсайты группируются, статус → consolidated
  → Агент или Доминика создаёт артефакт из консолидированных инсайтов
  → Артефакт проходит фактчекинг (cron еженедельно)
  → last_verified обновляется, артефакт остаётся актуальным
```

### Типы инсайтов

- **error** — ошибка/баг в коде, конфиге, документации
- **decision** — принятое архитектурное или процессное решение
- **finding** — результат разведки, поиска, анализа
- **pattern** — повторяющийся паттерн в работе
- **anti-pattern** — антипаттерн, чего не стоит делать
- **insight** — общий инсайт, не попадающий в другие категории

### Критерии хорошего инсайта

- **Конкретный** — не «что-то не так», а «файл X содержит Y → Z»
- **Воспроизводимый** — другой агент может проверить
- **Полезный** — помогает избежать ошибки или улучшить процесс
- **Актуальный** — относится к текущему состоянию системы

### Команды

```bash
# Добавить инсайт
python3 artifact_insights.py add \
  --content "Описание" \
  --source "dominika" \
  --type "finding" \
  --confidence "high" \
  --context "контекст" \
  --tags "тег1,тег2"

# Список инсайтов
python3 artifact_insights.py list --status new --limit 20

# Консолидация (группировка и повышение статуса)
python3 artifact_insights.py consolidate

# Консолидация без записи (dry-run)
python3 artifact_insights.py consolidate --dry-run

# Подтвердить инсайт
python3 artifact_insights.py verify --id INS-XXX

# Статистика
python3 artifact_insights.py stats
```

### Cron-задачи

- **artifact-insights-consolidate** — каждые 60 минут, консолидирует новые инсайты
- **artifact-factcheck** — еженедельно (понедельник 06:00 MSK), проверяет актуальность артефактов

### Важно

- Один инсайт = одна конкретная находка
- Не записывать очевидное или уже задокументированное
- При сомнениях — лучше записать, чем пропустить
- Дубликаты отсеиваются автоматически (content + source)

---

*Документ живёт в `projects/artifact-pulse/ARTIFACT_SYSTEM_GUIDE.md`*
*Обновлён: 2026-06-17*
