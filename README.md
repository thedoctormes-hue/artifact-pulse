# 🦉 Artifact Pulse v4.2.0

**Система мониторинга здоровья артефактов и управления инсайтами LabDoctorM.**

Два контура:
- **Артефакты** — мониторинг ADR, паттернов, правил, инцидентов (health check, граф, старение)
- **Инсайты** — сбор из сессий, семантическая дедупликация, консолидация, поиск через FAISS + bge-m3

## Документация
- `docs/ARCHITECTURE.md` — полная архитектура системы
- `docs/insights/README.md` — подробная документация по системе инсайтов

Ядро — `Artifact` dataclass (`artifact_types.py`) с dict-совместимостью (`__getitem__`, `get`).
Все модули работают с `Artifact` напрямую, без промежуточных адаптеров.

## Быстрый старт

```bash
# Установка
cd /root/LabDoctorM/projects/artifact-pulse
pip3 install -e .

# Health check
artifact-health --verbose

# Поиск по артефактам
artifact-search "VPN" --limit 5

# Проверка ссылок
artifact-links

# Старение (dry-run)
artifact-aging --dry-run

# Мониторинг + алерты
artifact-monitor

# Граф зависимостей
artifact-graph --format html --output /tmp/graph.html

# Происхождение и достоверность
artifact-provenance --report

# Структурные ограничения
artifact-constraints

# Нормализация frontmatter
artifact-normalize --check

# Аудит-отчёт
artifact-audit

# Changelog
artifact-changelog --generate-changelog --since 30
```

## Структура проекта

```
artifact-pulse/
├── config/
│ └── artifact_dirs.yaml # Пути к папкам артефактов и файлам состояния
├── scripts/
│ ├── evolve_orchestrator.sh # Оркестратор эволюции (инсайты → артефакты)
│ └── self_evolve.sh # Автономная эволюция (systemd timer)
├── tests/
│ └── test_artifact_system.py # 108 тестов
├── artifact_types.py # Artifact dataclass — каноническое представление артефакта
├── artifact_core.py # Ядро: парсинг frontmatter, загрузка артефактов
├── config_loader.py # Загрузчик конфигурации (YAML → Path)
├── artifact_health.py # Health check (9 измерений, score 0-100)
├── artifact_link_checker.py # Проверка ссылок, orphans, broken links
├── artifact_graph.py # Граф зависимостей (DOT/JSON/HTML с D3.js)
├── artifact_aging.py # Старение: active → stale → archived
├── artifact_stats.py # Статистика, рейтинг, цитирования
├── artifact_changelog.py # Версионирование, CHANGELOG.md
├── artifact_provenance.py # Происхождение, confidence decay, верификация
├── artifact_constraints.py # Структурные ограничения, циклы, противоречия
├── artifact_monitor.py # Тренды, алерты, health history (JSONL)
├── search_artifacts.py # Полнотекстовый поиск с persistent index
├── normalize_frontmatter.py # Валидация и нормализация frontmatter
├── audit_report.py # Комплексный аудит-отчёт (JSON)
├── pyproject.toml # Пакет artifact-pulse v4.1.0, 11 entry points
└── README.md
```

## Конфигурация

Все пути задаются в `config/artifact_dirs.yaml`:

```yaml
lab_dir: /root/LabDoctorM
artifact_dirs:
 pattern: patterns
 adr: adr
 rule: rules
 spec: specs
 incident: incidents
 metric: metrics
```

Скрипты автоматически загружают конфиг через `config_loader.py`.

## Health Check — 9 измерений

| Измерение | Вес | Описание |
|-----------|-----|----------|
| frontmatter | 20% | Валидность YAML frontmatter |
| links | 15% | Целостность ссылок, broken links, orphans |
| aging | 15% | Старение: stale, outdated |
| duplicates | 10% | Дубликаты по заголовкам |
| code_refs | 10% | Покрытие код-референсами |
| provenance | 15% | last_verified, confidence, source |
| constraints | 10% | Структурные ограничения |
| insights | 5% | Очередь инсайтов |
| infrastructure | 5% | Наличие скриптов, changelog |

Итоговый **score: 0-100**.

## Типы артефактов

| Тип | Префикс | Папка | Статусы |
|-----|---------|-------|---------|
| ADR | ADR- | adr/ | proposed, accepted, rejected, deprecated, superseded, archived, active, draft |
| Pattern | PAT- | patterns/ | draft, active, deprecated, archived, accepted, proposed |
| Rule | RUL- | rules/ | draft, active, deprecated, archived, pending, accepted, proposed |
| Backlog | BL- | specs/ | pending, in_progress, done, cancelled, archived, active, open, closed, resolved, accepted, proposed |
| Incident | INC- | incidents/ | open, investigating, resolved, closed, archived, pending, active |
| Metric | MET- | metrics/ | active, deprecated, archived, draft, pending, accepted |

## Зависимости

- Python 3.10+
- PyYAML >= 6.0

## Тесты

```bash
cd /root/LabDoctorM/projects/artifact-pulse
python3 -m pytest tests/ -v
# 108 tests, all passing
```

## Документация

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура системы, компоненты, потоки данных
- [docs/ADR/](docs/ADR/) — Architecture Decision Records (ключевые решения)
- [CHANGELOG.md](CHANGELOG.md) — история изменений
- [ARTIFACT_SYSTEM_GUIDE.md](ARTIFACT_SYSTEM_GUIDE.md) — руководство по системе артефактов для каждого лаборанта
- `templates/` — шаблоны для всех типов артефактов (ADR, PAT, RUL, INC, BL, MET)
- `systemd/` — unit-файлы для systemd таймеров

## Лицензия

Внутренний проект LabDoctorM.
