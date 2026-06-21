#!/bin/bash
# self_evolve.sh v3 — оркестратор эволюции лаборатории
#
# Запускается по таймеру (каждые 6 часов) или вручную.
# Координирует: capture → consolidate → reflect → artifact → audit
#
# Использование:
#   self_evolve.sh [--full] [--capture-only] [--consolidate-only] [--audit-only] [--dry-run]

set -euo pipefail

SCRIPT_DIR="/root/LabDoctorM/projects/artifact-pulse"
EVOLVE_SCRIPTS="/root/LabDoctorM/.qwen/scripts"
LOG_FILE="/root/LabDoctorM/.qwen/artifacts/evolution.log"
LOCK_FILE="/tmp/self_evolve.lock"

# ── Флаги ─────────────────────────────────────────
MODE="full"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)            MODE="full"; shift ;;
        --capture-only)    MODE="capture"; shift ;;
        --consolidate-only) MODE="consolidate"; shift ;;
        --audit-only)      MODE="audit"; shift ;;
        --dry-run)         DRY_RUN=true; shift ;;
        *)                 echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# ── Lock ──────────────────────────────────────────
if [[ -f "$LOCK_FILE" ]]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [[ -n "$LOCK_PID" ]] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "Another self_evolve is running (PID: $LOCK_PID). Exiting."
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

# ── Логирование ───────────────────────────────────
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

# ── Начало ────────────────────────────────────────
log "═══ SELF_EVOLVE v3 START (mode: $MODE, dry_run: $DRY_RUN) ═══"

DRY_RUN_FLAG=""
[[ "$DRY_RUN" == "true" ]] && DRY_RUN_FLAG="--dry-run"

# ── Шаг 1: Консолидация ───────────────────────────
if [[ "$MODE" == "full" ]] || [[ "$MODE" == "consolidate" ]]; then
    log "── Step 1: Consolidation ──"
    if [[ -f "$SCRIPT_DIR/insights_consolidator.sh" ]]; then
        DRY_RUN=$DRY_RUN \
        QUEUE_FILE="/root/LabDoctorM/.qwen/artifacts/insights_queue.json" \
        MEMORY_DIR="/root/.qwen/projects/-root-LabDoctorM/memory" \
        SIMILARITY_THRESHOLD=85 \
        REFLECTION_THRESHOLD=3 \
        MAX_REFLECTIONS=3 \
        bash "$EVOLVE_SCRIPTS/insights_consolidator.sh" $DRY_RUN_FLAG 2>&1 | while read line; do
            log "  consolidate: $line"
        done || log "  consolidate: FAILED (exit $?)"
    else
        log "  SKIP: insights_consolidator.sh not found"
    fi
fi

# ── Шаг 2: Артефактизация ─────────────────────────
if [[ "$MODE" == "full" ]]; then
    log "── Step 2: Artifact promotion ──"
    # Ищем инсайты с confirmations >= 2 (готовы к артектизации)
    PROMOTABLE=$(python3 -c "
import json, os
queue_file = '/root/LabDoctorM/.qwen/artifacts/insights_queue.json'
if not os.path.exists(queue_file):
    print(0)
else:
    with open(queue_file) as f:
        q = json.load(f)
    promotable = [i for i in q['insights'] if i.get('confirmations', 0) >= 2 and i.get('status') == 'consolidated']
    print(len(promotable))
" 2>/dev/null || echo 0)

    log "  Promotable insights: $PROMOTABLE"

    if [[ $PROMOTABLE -gt 0 ]]; then
        log "  → $PROMOTABLE insights ready for artifact creation"
        if [[ -f "$SCRIPT_DIR/evolve_orchestrator.sh" ]]; then
            DRY_RUN=$DRY_RUN bash "$EVOLVE_SCRIPTS/evolve_orchestrator.sh" \
                --min-confirmations 2 $DRY_RUN_FLAG 2>&1 | while read line; do
                log "  evolve: $line"
            done || log "  evolve: FAILED (exit $?)"
        else
            log "  SKIP: evolve_orchestrator.sh not found"
        fi
    fi
fi

# ── Шаг 3: Аудит ──────────────────────────────────
if [[ "$MODE" == "full" ]] || [[ "$MODE" == "audit" ]]; then
    log "── Step 3: Audit ──"
    SCRIPT_DIR="/root/LabDoctorM/projects/artifact-pulse"
    if [[ -f "$SCRIPT_DIR/normalize_frontmatter.py" ]]; then
        ERRORS=$(python3 "$SCRIPT_DIR/normalize_frontmatter.py" --check --path /root/LabDoctorM 2>&1 | grep -c "❌" || true)
        log "  Frontmatter errors: $ERRORS"
        if [[ $ERRORS -gt 0 ]]; then
            log "  ⚠️  $ERRORS artifacts have frontmatter issues"
        else
            log "  ✅ All artifacts valid"
        fi
    else
        log "  SKIP: normalize_frontmatter.py not found"
    fi
fi

# ── Шаг 4: Статистика ─────────────────────────────
if [[ "$MODE" == "full" ]]; then
    log "── Step 4: Statistics ──"
    python3 -c "
import json, os

# Очередь
queue_file = '/root/LabDoctorM/.qwen/artifacts/insights_queue.json'
if os.path.exists(queue_file):
    with open(queue_file) as f:
        q = json.load(f)
    total = len(q.get('insights', []))
    new = len([i for i in q['insights'] if i.get('status') == 'new'])
    consolidated = len([i for i in q['insights'] if i.get('status') == 'consolidated'])
    print(f'  Queue: {total} total, {new} new, {consolidated} consolidated')
else:
    print('  Queue: empty')

# Артефакты
artifact_dirs = {
    'adr': '/root/LabDoctorM/adr',
    'patterns': '/root/LabDoctorM/patterns',
    'rules': '/root/LabDoctorM/rules',
    'specs': '/root/LabDoctorM/specs',
    'incidents': '/root/LabDoctorM/incidents',
    'metrics': '/root/LabDoctorM/metrics',
}
total_artifacts = 0
for name, path in artifact_dirs.items():
    if os.path.exists(path):
        count = len([f for f in os.listdir(path) if f.endswith('.md') and 'template' not in f.lower()])
        total_artifacts += count
        print(f'  {name}: {count}')
print(f'  Total artifacts: {total_artifacts}')

# Память
mem_dir = '/root/.qwen/projects/-root-LabDoctorM/memory'
if os.path.exists(mem_dir):
    mem_files = [f for f in os.listdir(mem_dir) if f.endswith('.md')]
    print(f'  Memory files: {len(mem_files)}')
" 2>&1 | while read line; do
        log "$line"
    done
fi

# ── Шаг 5: Artifact stats ──────────────────────────
if [[ "$MODE" == "full" ]]; then
    log "── Step 5: Artifact stats ──"
    if [[ -f "$SCRIPT_DIR/artifact_stats.py" ]]; then
        python3 "$SCRIPT_DIR/artifact_stats.py" --update --top 5 2>&1 | while read line; do
            log "  stats: $line"
        done
    fi
fi

# ── Шаг 6: Changelog ───────────────────────────────
if [[ "$MODE" == "full" ]]; then
    log "── Step 6: Changelog ──"
    if [[ -f "$SCRIPT_DIR/artifact_changelog.py" ]]; then
        python3 "$SCRIPT_DIR/artifact_changelog.py" --generate-changelog --since 7 2>&1 | while read line; do
            log "  changelog: $line"
        done
    fi
fi

# ── Шаг 7: Provenance ─────────────────────────────
if [[ "$MODE" == "full" ]] || [[ "$MODE" == "audit" ]]; then
    log "── Step 7: Provenance ──"
    if [[ -f "$SCRIPT_DIR/artifact_provenance.py" ]]; then
        PROV_SCORE=$(python3 "$SCRIPT_DIR/artifact_provenance.py" 2>&1 | grep "Provenance Score:" | grep -oP '\d+' | head -1)
        log "  Provenance score: ${PROV_SCORE:-N/A}"
        if [[ -n "${PROV_SCORE:-}" ]] && [[ "$PROV_SCORE" -lt 80 ]]; then
            log "  ⚠️  Provenance score below threshold (80)"
        fi
    else
        log "  SKIP: artifact_provenance.py not found"
    fi
fi

# ── Шаг 8: Constraints ─────────────────────────────
if [[ "$MODE" == "full" ]] || [[ "$MODE" == "audit" ]]; then
    log "── Step 8: Constraints ──"
    if [[ -f "$SCRIPT_DIR/artifact_constraints.py" ]]; then
        python3 "$SCRIPT_DIR/artifact_constraints.py" 2>&1 | while read line; do
            log "  constraints: $line"
        done
    else
        log "  SKIP: artifact_constraints.py not found"
    fi
fi

# ── Шаг 9: Monitor snapshot ───────────────────────
if [[ "$MODE" == "full" ]]; then
    log "── Step 9: Monitor snapshot ──"
    if [[ -f "$SCRIPT_DIR/artifact_monitor.py" ]]; then
        python3 "$SCRIPT_DIR/artifact_monitor.py" 2>&1 | while read line; do
            log "  monitor: $line"
        done
    else
        log "  SKIP: artifact_monitor.py not found"
    fi
fi

# ── Завершение ────────────────────────────────────
log "═══ SELF_EVOLVE v3 COMPLETE ═══"
