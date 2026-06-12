---
name: Artifact Pulse
type: monitoring
status: active
owner: owl
priority: medium
stack: [Python]
version: "1.0.0"
path: projects/artifact-pulse
created: "2026-06-04"
---

# Artifact Pulse

Система мониторинга здоровья артефактов LabDoctorM. Отслеживает целостность, свежесть, связность и достоверность артефактов лаборатории.

## Владелец
Ворон (owl)

## Компоненты
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

## Документация
- [ARTIFACT_SYSTEM_GUIDE.md](ARTIFACT_SYSTEM_GUIDE.md) — руководство по системе
- [AUDIT.md](AUDIT.md) — аудит
