---
name: Artifact Pulse
owner: DoctorM&Ai
type: monitoring
status: active
priority: high
stack: [Python]
version: "2.0.0"
path: projects/artifact-pulse
created: "2026-06-04"
updated: "2026-06-18"
---

# Artifact Pulse

Система мониторинга здоровья артефактов и управления инсайтами LabDoctorM.

Два контура:
- **Артефакты** — мониторинг целостности, свежести, связности и достоверности артефактов (ADR, паттерны, правила, инциденты)
- **Инсайты** — сбор из сессий агентов, семантическая дедупликация, консолидация и поиск знаний

## Компоненты

### Артефакты (monitoring)
- `artifact_core.py` — ядро системы
- `artifact_health.py` — проверка здоровья (7 измерений)
- `artifact_graph.py` — визуализация графа зависимостей
- `artifact_link_checker.py` — проверка ссылок
- `artifact_provenance.py` — отслеживание происхождения
- `artifact_aging.py` — анализ устаревания
- `artifact_changelog.py` — журнал изменений
- `artifact_constraints.py` — проверка ограничений
- `artifact_monitor.py` — мониторинг
- `artifact_stats.py` — статистика
- `audit_report.py` — аудит-отчёт
- `normalize_frontmatter.py` — нормализация frontmatter

### Инсайты (knowledge)
- `artifact_insights.py` — ядро системы инсайтов (SQLite + FAISS, статус-флоу)
- `session_insights_miner.py` — добытчик инсайтов из сессий
- `scripts/build_faiss_index.py` — построение FAISS индекса
- `scripts/migrate_to_sqlite.py` — миграция из JSON в SQLite
- `docs/insights/README.md` — подробное руководство

## Документация
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — полная архитектура системы
- [ARTIFACT_SYSTEM_GUIDE.md](ARTIFACT_SYSTEM_GUIDE.md) — руководство по системе артефактов
- [docs/insights/README.md](docs/insights/README.md) — руководство по системе инсайтов
- [AUDIT.md](AUDIT.md) — аудит

## Текущий статус
- **Статус:** active (в работе)
- **Приоритет:** high (критически важная инфраструктура)
- **Последнее обновление:** 2026-06-18 (завершены этапы M1–M4)
- **Тестовое покрытие:** 167 passed, 10 skipped
- **Размеры данных:** insights.db ~1.2 MB, insights.faiss 941 KB