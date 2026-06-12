# ADR-003: Block-style YAML для list в rebuild_frontmatter

## Статус
Accepted

## Контект
`yaml.safe_load` автоматически парсит строки вида `"2026-06-09: text"` как `{datetime.date(2026, 6, 9): 'text'}` когда они находятся в inline list. Это происходит в history entries артефактов.

## Решение
В `rebuild_frontmatter()` генерировать block-style YAML для всех списков:
```yaml
tags:
  - item1
  - item2
```

Вместо inline:
```yaml
tags: [item1, item2]
```

Для значений, начинающихся с цифры и содержащих двоеточие, добавить кавычки через `_needs_quoting()`.

## Последствия
- **Плюсы:** полное устранение type coercion для history entries
- **Плюсы:** предсказуемое поведение YAML парсера
- **Минусы:** block-style увеличивает размер файла (незначительно)
- **Минусы:** требует миграции существующих inline list (не критично)
