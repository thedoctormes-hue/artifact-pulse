# ADR-002: Health Score — 9 измерений с весами

## Статус
Accepted

## Контект
Нужна единая метрика качества системы артефактов, которая:
- Показывает общее здоровье (0-100)
- Выявляет конкретные проблемы для исправления
- Отслеживает тренды во времени

## Решение
9 измерений с весами, суммарный weighted score:

| Измерение | Вес | Модуль |
|-----------|-----|--------|
| frontmatter | 20% | artifact_health.py |
| links | 15% | artifact_link_checker.py |
| aging | 15% | artifact_aging.py |
| provenance | 15% | artifact_provenance.py |
| duplicates | 10% | artifact_health.py |
| constraints | 10% | artifact_constraints.py |
| code_refs | 10% | artifact_health.py |
| insights | 5% | artifact_health.py |
| infrastructure | 5% | artifact_health.py |

## Последствия
- **Плюсы:** одна цифра для дашборда, детализация для диагностики
- **Минусы:** веса субъективны, требуют калибровки на реальных данных
- **Минусы:**новые измерения требуют перебалансировки весов
