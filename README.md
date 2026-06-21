# 🦉 Artifact Pulse

**Система мониторинга здоровья артефактов LabDoctorM.**

Отслеживает целостность, свежесть, связность и достоверность артефактов лаборатории:
ADR, паттерны, правила, спецификации, инциденты, метрики.

## Архитектура

```
artifact-pulse/
├── config/
│   └── artifact_dirs.yaml      # Пути к папкам артефактов и файлам состояния
├── src/
│   ├── config_loader.py        # Загрузчик конфига (YAML → Path)
│   ├── artifact_health.py       # Health check (9 измерений, score 0-100)
│   ├── artifact_link_checker.py # Проверка ссылок, orphans, broken links
│   ├── artifact_graph.py        # Граф зависимостей (DOT/JSON/HTML)
│   ├── artifact_aging.py        # Старение: active → stale → archived
│   ├── artifact_stats.py        # Статистика, рейтинг, цитирования
│   ├── artifact_changelog.py    # Версионирование, CHANGELOG.md
│   ├── artifact_provenance.py   # Происхождение, confidence decay, верификация
│   ├── artifact_constraints.py  # Структурные ограничения, противоречия
│   ├── artifact_monitor.py      # Тренды, алерты, health history
│   ├── search_artifacts.py      # Полнотекстовый поиск по артефактам
│   ├── normalize_frontmatter.py # Валидация и нормализация frontmatter
│   └── audit_report.py          # Комплексный аудит-отчёт
├── scripts/
│   ├── evolve_orchestrator.sh   # Оркестратор эволюции артефактов
│   └── self_evolve.sh           # Автономная эволюция (cron)
├── tests/
│   └── test_artifact_system.py  # 53 теста
└── README.md
```

## Быстрый старт

```bash
# Health check
python3 src/artifact_health.py --verbose

# Поиск по артефактам
python3 src/search_artifacts.py "VPN" --limit 5

# Проверка ссылок
python3 src/artifact_link_checker.py

# Старение (dry-run)
python3 src/artifact_aging.py --dry-run

# Мониторинг + алерты
python3 src/artifact_monitor.py --check
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

| Измерение | Описание |
|-----------|----------|
| frontmatter | Валидность YAML frontmatter |
| links | Целостность ссылок, broken links, orphans |
| aging | Старение: stale, outdated |
| duplicates | Дубликаты по заголовкам |
| code_refs | Покрытие код-референсами |
| insights_queue | Очередь инсайтов |
| changelog | Наличие CHANGELOG.md |
| scripts | Наличие всех скриптов |
| provenance | last_verified, confidence, source |

Итоговый **score: 0-100**.

## Зависимости

- Python 3.10+
- PyYAML (`pip install pyyaml`)

## Тесты

```bash
python3 -m pytest tests/ -v
# или
python3 tests/test_artifact_system.py
```

## Документация

- [ARTIFACT_SYSTEM_GUIDE.md](ARTIFACT_SYSTEM_GUIDE.md) — руководство по системе артефактов для каждого лаборанта
- `templates/` — шаблоны для всех типов артефактов (ADR, PAT, RUL, INC, BL, MET)
- `systemd/` — unit-файлы для systemd таймеров

## Лицензия

Внутренний проект LabDoctorM.
