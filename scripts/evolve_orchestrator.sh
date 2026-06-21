#!/bin/bash
# evolve_orchestrator.sh v2 — создание качественных артефактов из инсайтов
#
# Читает инсайты из insights_queue.json, классифицирует по типу артефакта,
# генерирует структурированный .md из шаблона + контекста инсайта,
# ищет упоминания файлов для линковки артефакт↔код.
#
# Использование:
#   evolve_orchestrator.sh [--dry-run] [--min-confirmations N] [--type TYPE]

set -euo pipefail

DRY_RUN=false
MIN_CONFIRMATIONS=1
FILTER_TYPE=""  # пустой = все типы

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)          DRY_RUN=true; shift ;;
        --min-confirmations) MIN_CONFIRMATIONS="$2"; shift 2 ;;
        --type)             FILTER_TYPE="$2"; shift 2 ;;
        *)                  echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

QUEUE_FILE="/root/LabDoctorM/.qwen/artifacts/insights_queue.json"
MEMORY_DIR="/root/.qwen/projects/-root-LabDoctorM/memory"
LAB_DIR="/root/LabDoctorM"

log() { echo "[evolve] $*"; }

# ── Классификация инсайта по типу артефакта ────────
# Вход: текст инсайта
# Выход: artifact_type (adr|pattern|rule|spec|incident|metric)
classify_insight() {
    local text="$1"
    local type_hint="$2"  # из insight.type (discovery|breakage|improvement)

    # Приоритет: явный тип из инсайта
    case "$type_hint" in
        breakage)    echo "incident"; return ;;
        improvement) echo "pattern"; return ;;
    esac

    # Эвристики по содержимому
    if echo "$text" | grep -qiE "сломал|ошибка|баг|падение|SIGABRT|crash|broken|fix|исправл|не работа"; then
        echo "incident"
    elif echo "$text" | grep -qiE "решил|решение|выбрал|ADR|архитекту|design decision|trade.off|компромисс"; then
        echo "adr"
    elif echo "$text" | grep -qiE "правило|rule|never|always|must|should|запрещено|обязательно|convention"; then
        echo "rule"
    elif echo "$text" | grep -qiE "спецификация|spec|API|endpoint|интерфейс|контракт|schema|protocol"; then
        echo "spec"
    elif echo "$text" | grep -qiE "метрика|metric|SLO|SLI|uptime|latency|производительность|нагрузка"; then
        echo "metric"
    else
        echo "pattern"
    fi
}

# ── Извлечение упоминаний файлов из текста ──────────
# Выводит список файлов через запятую
extract_file_refs() {
    local text="$1"
    echo "$text" | grep -oE '(/[a-zA-Z0-9_./-]+\.(ts|js|py|sh|md|json|yaml|yml|toml|cfg|conf))' | sort -u | tr '\n' ',' | sed 's/,$//'
}

# ── Извлечение упоминаний артефактов из текста ──────
extract_artifact_refs() {
    local text="$1"
    echo "$text" | grep -oE '(ADR|RUL|PAT|BL|INS|INC|SPEC)-[0-9]+' | sort -u | tr '\n' ',' | sed 's/,$//'
}

# ── Генерация slug из заголовка ─────────────────────
generate_slug() {
    local title="$1"
    echo "$title" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9а-яё ]//g' | tr ' ' '-' | sed 's/--*/-/g' | sed 's/^-//;s/-$//' | cut -c1-50
}

# ── Определение категории паттерна ──────────────────
classify_pattern_category() {
    local text="$1"
    if echo "$text" | grep -qiE "безопасность|security|auth|уязвим|vulnerability|XSS|CSRF|inject"; then
        echo "security"
    elif echo "$text" | grep -qiE "deploy|деплой|docker|systemd|nginx|CI/CD"; then
        echo "deploy"
    elif echo "$text" | grep -qiE "архитектура|architecture|микросервис|monolith|layer|слои"; then
        echo "architecture"
    elif echo "$text" | grep -qiE "UX|интерфейс|UI|frontend|sidebar|навигация"; then
        echo "ux"
    elif echo "$text" | grep -qiE "infra|инфраструктур|сервер|network|VPN|туннель"; then
        echo "infra"
    elif echo "$text" | grep -qiE "test|тест|mock|coverage|pytest|jest"; then
        echo "testing"
    else
        echo "coding"
    fi
}

# ── Определение severity инцидента ──────────────────
classify_severity() {
    local text="$1"
    if echo "$text" | grep -qiE "CRITICAL|critical|данные скомпрометированы|система не работает|SIGABRT|полный отказ"; then
        echo "🔴 CRITICAL"
    elif echo "$text" | grep -qiE "HIGH|high|серьёзн|немедленн|срочн"; then
        echo "🟠 HIGH"
    elif echo "$text" | grep -qiE "MEDIUM|medium|средн|обходной путь"; then
        echo "🟡 MEDIUM"
    else
        echo "🟢 LOW"
    fi
}

# ── Определение категории правила ───────────────────
classify_rule_category() {
    local text="$1"
    if echo "$text" | grep -qiE "security|безопасность|auth|secret|token|key"; then
        echo "security"
    elif echo "$text" | grep -qiE "deploy|деплой|systemd|docker"; then
        echo "deploy"
    elif echo "$text" | grep -qiE "style|стиль|format|именование|convention"; then
        echo "coding-style"
    elif echo "$text" | grep -qiE "API|endpoint|REST|GraphQL"; then
        echo "api"
    elif echo "$text" | grep -qiE "test|тест|mock|coverage"; then
        echo "testing"
    elif echo "$text" | grep -qiE "doc|документация|comment|README"; then
        echo "docs"
    else
        echo "coding"
    fi
}

# ── Получение следующего ID для типа артефакта ──────
get_next_id() {
    local dir="$1"
    local prefix="$2"
    local ext="${3:-md}"
    local max=0

    if [[ -d "$dir" ]]; then
        while IFS= read -r f; do
            local num
            num=$(echo "$f" | grep -oE "${prefix}-([0-9]+)" | grep -oE '[0-9]+' || echo 0)
            if [[ $num -gt $max ]]; then
                max=$num
            fi
        done < <(find "$dir" -maxdepth 1 -name "${prefix}-*.${ext}" -type f 2>/dev/null)
    fi
    printf "%s-%03d" "$prefix" $((max + 1))
}

# ── Quality Gate — валидация качества перед созданием ─
# Возвращает 0 = прошёл, 1 = отклонён
# Выводит причину отказа в stdout
quality_gate() {
    local artifact_type="$1"
    local title="$2"
    local content="$3"
    local confirmations="$4"

    # 1. Минимальная длина контента
    local content_len=${#content}
    if [[ $content_len -lt 30 ]]; then
        echo "REJECT: content too short ($content_len chars, min 30)"
        return 1
    fi

    # 2. Заголовок не должен быть пустым или обрезанным "?"
    if [[ -z "$title" ]] || [[ "$title" == "?" ]] || [[ ${#title} -lt 5 ]]; then
        echo "REJECT: title too short or empty ('$title')"
        return 1
    fi

    # 3. Контент не должен содержать только технический мусор
    local meaningful_words
    meaningful_words=$(echo "$content" | grep -oE '[a-zA-Zа-яёА-ЯЁ]{4,}' | wc -l)
    if [[ $meaningful_words -lt 3 ]]; then
        echo "REJECT: not enough meaningful words ($meaningful_words, min 3)"
        return 1
    fi

    # 4. Проверка на дубликат по заголовку (fuzzy)
    local title_lower
    title_lower=$(echo "$title" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9а-яё ]//g')
    local dir
    case "$artifact_type" in
        pattern)  dir="$LAB_DIR/patterns" ;;
        adr)      dir="$LAB_DIR/adr" ;;
        rule)     dir="$LAB_DIR/rules" ;;
        spec)     dir="$LAB_DIR/specs" ;;
        incident) dir="$LAB_DIR/incidents" ;;
        metric)   dir="$LAB_DIR/metrics" ;;
    esac
    if [[ -d "$dir" ]]; then
        local dup
        dup=$(find "$dir" -name "*.md" -type f -exec grep -liF "$title" {} \; 2>/dev/null | head -1)
        if [[ -n "$dup" ]]; then
            echo "REJECT: duplicate title found in $dup"
            return 1
        fi
    fi

    # 5. Минимум 2 подтверждения для auto-generated (если не переопределено)
    if [[ $confirmations -lt 1 ]]; then
        echo "REJECT: insufficient confirmations ($confirmations, min 1)"
        return 1
    fi

    # 6. Контент не должен быть только из спецсимволов/путей
    local non_path_words
    non_path_words=$(echo "$content" | grep -vE '^(/|[[:space:]]*$)' | grep -oE '[a-zA-Zа-яёА-ЯЁ]{3,}' | wc -l)
    if [[ $non_path_words -lt 2 ]]; then
        echo "REJECT: content is mostly file paths, not meaningful text"
        return 1
    fi

    echo "PASS"
    return 0
}

# ── Создание артефакта из шаблона + контекста ────────
create_artifact() {
    local artifact_type="$1"
    local title="$2"
    local content="$3"
    local insight_id="$4"
    local confirmations="$5"
    local file_refs="$6"
    local artifact_refs="$7"
    local now
    now=$(date -u '+%Y-%m-%dT%H:%M:%S+00:00')

    local dir prefix
    case "$artifact_type" in
        pattern)  dir="$LAB_DIR/patterns";  prefix="PAT" ;;
        adr)      dir="$LAB_DIR/adr";       prefix="ADR" ;;
        rule)     dir="$LAB_DIR/rules";     prefix="RUL" ;;
        spec)     dir="$LAB_DIR/specs";     prefix="SPEC" ;;
        incident) dir="$LAB_DIR/incidents"; prefix="INC" ;;
        metric)   dir="$LAB_DIR/metrics";   prefix="MET" ;;
        *)        log "  ERROR: unknown artifact type: $artifact_type"; return 1 ;;
    esac

    local artifact_id
    artifact_id=$(get_next_id "$dir" "$prefix")
    local slug
    slug=$(generate_slug "$title")
    local filename="${dir}/${artifact_id}-${slug}.md"

    # Проверка дубликата
    if [[ -f "$filename" ]]; then
        log "  SKIP: $filename already exists"
        return 0
    fi

    # Генерация контента по типу
    case "$artifact_type" in
        pattern)
            local category
            category=$(classify_pattern_category "$content")
            cat > "$filename" <<ARTIFACT
---
id: ${artifact_id}
type: pattern
title: "${title}"
status: active
category: ${category}
author: evolve_orchestrator
created: ${now}
updated: ${now}
last_verified: ${now}
confidence: medium
confirmations: ${confirmations}
source_insight: ${insight_id}
source: evolve_orchestrator
tags: [${category}, auto-generated]
---

# ${artifact_id}: ${title}

## Категория
${category}

## Контекст
${content}

## Решение
<!-- TODO: дополнить решение на основе контекста инсайта -->

## Примеры
<!-- TODO: добавить примеры применения -->

## Критерии применимости
- [ ] Условие определяется из контекста

## Связанные инсайты
- ${insight_id} — ${title}

## Связанные артефакты
${artifact_refs:+- ${artifact_refs}}

## Затронутые файлы
${file_refs:+- ${file_refs}}

## Примечания
Автоматически создано из инсайта ${insight_id} (confirmations: ${confirmations}).
Требует ручной проверки и дополнения.
ARTIFACT
            ;;

        adr)
            cat > "$filename" <<ARTIFACT
---
id: ${artifact_id}
type: adr
title: "${title}"
status: proposed
author: evolve_orchestrator
created: ${now}
updated: ${now}
confirmations: ${confirmations}
last_verified: ${now}
confidence: medium
source_insight: ${insight_id}
source: evolve_orchestrator
tags: [architecture, decision, auto-generated]
---

# ${artifact_id}: ${title}

## Статус
proposed

## Контекст
${content}

## Решение
<!-- TODO: дополнить описание выбранного решения -->

## Последствия
- ✅ Позитивные последствия — определить из контекста
- ⚠️ Негативные последствия / компромиссы — определить из контекста
- 📋 Что нужно сделать — определить из контекста

## Альтернативы
- **Вариант 1:** <!-- TODO: описание -->
  - Плюсы: <!-- TODO -->
  - Минусы: <!-- TODO -->
  - Статус: отклонён / принят

## Связанные инсайты
- ${insight_id} — ${title}

## Затронутые файлы
${file_refs:+- ${file_refs}}

## Примечания
Автоматически создано из инсайта ${insight_id} (confirmations: ${confirmations}).
Требует ручной проверки и утверждения.
ARTIFACT
            ;;

        rule)
            local category
            category=$(classify_rule_category "$content")
            cat > "$filename" <<ARTIFACT
---
id: ${artifact_id}
type: rule
title: "${title}"
status: active
category: ${category}
author: evolve_orchestrator
created: ${now}
updated: ${now}
confirmations: ${confirmations}
last_verified: ${now}
confidence: medium
source_insight: ${insight_id}
source: evolve_orchestrator
tags: [${category}, auto-generated]
---

# ${artifact_id}: ${title}

## Категория
${category}

## Описание
${content}

## Обязательно
- [ ] Требование определяется из контекста инсайта

## Исключения
<!-- TODO: описать когда правило не применяется -->

## Связанные инсайты
- ${insight_id} — ${title}

## Затронутые файлы
${file_refs:+- ${file_refs}}

## Примечания
Автоматически создано из инсайта ${insight_id} (confirmations: ${confirmations}).
Требует ручной проверки.
ARTIFACT
            ;;

        spec)
            cat > "$filename" <<ARTIFACT
---
id: ${artifact_id}
type: spec
title: "${title}"
status: draft
author: evolve_orchestrator
created: ${now}
updated: ${now}
confirmations: ${confirmations}
last_verified: ${now}
confidence: medium
source_insight: ${insight_id}
source: evolve_orchestrator
tags: [specification, auto-generated]
---

# ${artifact_id}: ${title}

## Обзор
${content}

## Интерфейс
<!-- TODO: описать API/интерфейс -->

## Поведение
<!-- TODO: описать ожидаемое поведение -->

## Ограничения
<!-- TODO: описать ограничения -->

## Связанные инсайты
- ${insight_id} — ${title}

## Затронутые файлы
${file_refs:+- ${file_refs}}

## Примечания
Автоматически создано из инсайта ${insight_id} (confirmations: ${confirmations}).
Требует ручной проверки.
ARTIFACT
            ;;

        incident)
            local severity
            severity=$(classify_severity "$content")
            cat > "$filename" <<ARTIFACT
---
id: ${artifact_id}
type: incident
title: "${title}"
status: open
severity: ${severity}
author: evolve_orchestrator
created: ${now}
updated: ${now}
confirmations: ${confirmations}
last_verified: ${now}
confidence: medium
source_insight: ${insight_id}
source: evolve_orchestrator
tags: [incident, auto-generated]
---

# ${artifact_id}: ${title}

## Описание
${content}

## Severity
${severity}

## Обнаружено
- **Источник:** evolve_orchestrator
- **Инсайт:** ${insight_id}

## Действия
- [ ] Проанализировать причину
- [ ] Определить исправление
- [ ] Проверить что исправление не сломало другое

## Связанные инсайты
- ${insight_id} — ${title}

## Затронутые файлы
${file_refs:+- ${file_refs}}

## Примечания
Автоматически создано из инсайта ${insight_id} (confirmations: ${confirmations}).
ARTIFACT
            ;;

        metric)
            cat > "$filename" <<ARTIFACT
---
id: ${artifact_id}
type: metric
title: "${title}"
status: active
author: evolve_orchestrator
created: ${now}
updated: ${now}
confirmations: ${confirmations}
last_verified: ${now}
confidence: medium
source_insight: ${insight_id}
source: evolve_orchestrator
tags: [metric, auto-generated]
---

# ${artifact_id}: ${title}

## Описание
${content}

## Измерение
<!-- TODO: описать как измерять -->

## Целевые значения
<!-- TODO: описать SLO/SLI -->

## Связанные инсайты
- ${insight_id} — ${title}

## Затронутые файлы
${file_refs:+- ${file_refs}}

## Примечания
Автоматически создано из инсайта ${insight_id} (confirmations: ${confirmations}).
Требует ручной проверки.
ARTIFACT
            ;;
    esac

    log "  CREATED: $filename ($artifact_type, $artifact_id)"
}

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

log "═══ EVOLVE_ORCHESTRATOR v2 START ═══"
log "  min_confirmations: $MIN_CONFIRMATIONS"
log "  filter_type: ${FILTER_TYPE:-all}"
log "  dry_run: $DRY_RUN"

if [[ ! -f "$QUEUE_FILE" ]]; then
    log "ERROR: queue file not found: $QUEUE_FILE"
    exit 1
fi

# ── Обработка инсайтов ─────────────────────────────
PROCESSED=0
CREATED=0
SKIPPED=0

while IFS= read -r insight; do
    [[ -z "$insight" ]] && continue

    # Парсинг полей
    local_id=$(echo "$insight" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
    local_status=$(echo "$insight" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
    local_type=$(echo "$insight" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('type',''))" 2>/dev/null || echo "")
    local_content=$(echo "$insight" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('content',''))" 2>/dev/null || echo "")
    local_title=$(echo "$insight" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title',''))" 2>/dev/null || echo "")
    local_confirmations=$(echo "$insight" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('confirmations',0))" 2>/dev/null || echo 0)

    [[ -z "$local_id" ]] && continue

    # Фильтр по статусу (skip только rejected/duplicate)
    if [[ "$local_status" == "rejected" ]] || [[ "$local_status" == "duplicate" ]]; then
        continue
    fi

    # Фильтр по confirmations
    if [[ "$local_confirmations" -lt "$MIN_CONFIRMATIONS" ]]; then
        continue
    fi

    # Фильтр по типу
    if [[ -n "$FILTER_TYPE" ]] && [[ "$local_type" != "$FILTER_TYPE" ]]; then
        continue
    fi

    PROCESSED=$((PROCESSED + 1))

    # Заголовок из контента (первые 80 символов)
    if [[ -z "$local_title" ]] || [[ "$local_title" == "?" ]]; then
        local_title=$(echo "$local_content" | head -c 80)
    fi

    # Классификация
    artifact_type=$(classify_insight "$local_content" "$local_type")
    log "  [$local_id] type=$local_type → artifact=$artifact_type, conf=$local_confirmations"

    # Извлечение ссылок
    file_refs=$(extract_file_refs "$local_content")
    artifact_refs=$(extract_artifact_refs "$local_content")

    if [[ -n "$file_refs" ]]; then
        log "    files: $file_refs"
    fi
    if [[ -n "$artifact_refs" ]]; then
        log "    artifacts: $artifact_refs"
    fi

    # Проверка: артефакт уже существует для этого инсайта?
    existing=$(find "$LAB_DIR" -name "*.md" -exec grep -l "source_insight: ${local_id}" {} \; 2>/dev/null | head -1)
    if [[ -n "$existing" ]]; then
        log "  SKIP: artifact already exists for $local_id → $existing"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Quality gate
    qg_result=$(quality_gate "$artifact_type" "$local_title" "$local_content" "$local_confirmations" 2>&1)
    if [[ "$qg_result" != "PASS" ]]; then
        log "  QG_FAIL: $qg_result → skipping $local_id"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        log "  DRY-RUN: would create $artifact_type → ${local_title}"
    else
        if create_artifact "$artifact_type" "$local_title" "$local_content" "$local_id" "$local_confirmations" "$file_refs" "$artifact_refs"; then
            CREATED=$((CREATED + 1))
        fi
    fi

done < <(python3 -c "
import json
with open('$QUEUE_FILE') as f:
    q = json.load(f)
for i in q.get('insights', []):
    print(json.dumps(i, ensure_ascii=False))
" 2>/dev/null)

log "═══ EVOLVE_ORCHESTRATOR v2 COMPLETE ═══"
log "  processed: $PROCESSED, created: $CREATED, skipped: $SKIPPED"
