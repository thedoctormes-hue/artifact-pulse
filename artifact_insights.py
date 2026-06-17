#!/usr/bin/env python3
"""
artifact_insights.py — Модуль приёма и консолидации инсайтов для artifact-pulse.

Использование:
  python3 artifact_insights.py add --content "..." --source "agent" --type "finding" [--confidence high] [--context "..."] [--tags "t1,t2"]
  python3 artifact_insights.py list [--status new] [--limit 20]
  python3 artifact_insights.py consolidate [--min-confidence 0.7] [--dry-run]
  python3 artifact_insights.py stats
  python3 artifact_insights.py verify --id INS-XXX
"""

import argparse
import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

QUEUE_PATH = (
    Path(__file__).parent.parent.parent / ".qwen" / "artifacts" / "insights_queue.json"
)
ARTIFACT_DIRS = {
    "adr": "adr/",
    "pattern": "patterns/",
    "rule": "rules/",
    "incident": "incidents/",
    "spec": "specs/",
    "metric": "metrics/",
}
VALID_TYPES = {"error", "decision", "finding", "pattern", "anti-pattern", "insight"}
VALID_CONFIDENCE = {"low": 0.3, "medium": 0.6, "high": 0.9}
VALID_STATUS = {"new", "consolidated", "promoted", "rejected", "archived"}


def load_queue() -> dict:
    if QUEUE_PATH.exists():
        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 3, "insights": []}


def save_queue(queue: dict):
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)


def generate_id(content: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    h = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"INS-{ts}-{h}"


def add_insight(
    content: str,
    source: str,
    insight_type: str,
    confidence: str = "medium",
    context: str = "",
    tags: str = "",
    tool: str = "",
) -> dict:
    if insight_type not in VALID_TYPES:
        print(
            f"Ошибка: неизвестный тип '{insight_type}'. Допустимые: {', '.join(sorted(VALID_TYPES))}"
        )
        sys.exit(1)

    if confidence not in VALID_CONFIDENCE:
        print(
            f"Ошибка: неизвестная уверенность '{confidence}'. Допустимые: {', '.join(sorted(VALID_CONFIDENCE.keys()))}"
        )
        sys.exit(1)

    queue = load_queue()

    # Дедупликация: проверяем последние 50 инсайтов на совпадение content
    for existing in queue["insights"][-50:]:
        if (
            existing["content"].strip() == content.strip()
            and existing["source"] == source
        ):
            print(
                f"Дубликат: инсайт уже существует как {existing['id']} (status: {existing['status']})"
            )
            return existing

    insight = {
        "id": generate_id(content),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool or "manual",
        "context": context,
        "content": content,
        "importance": VALID_CONFIDENCE[confidence],
        "status": "new",
        "confirmations": 0,
        "source": source,
        "type": insight_type,
        "confidence": confidence,
        "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
    }

    queue["insights"].append(insight)
    save_queue(queue)
    print(
        f"✅ Инсайт записан: {insight['id']} (type={insight_type}, confidence={confidence})"
    )
    return insight


def list_insights(status: str = None, limit: int = 20, source: str = None):
    queue = load_queue()
    insights = queue["insights"]

    if status:
        insights = [i for i in insights if i.get("status") == status]
    if source:
        insights = [i for i in insights if i.get("source") == source]

    total = len(insights)
    print(
        f"Всего инсайтов: {total}"
        + (f" (показано последние {limit})" if total > limit else "")
    )
    print()

    for i in insights[-limit:]:
        tags = ", ".join(i.get("tags", []))
        print(f"  [{i['status']}] {i['id']}")
        print(
            f"    type={i.get('type','?')}  confidence={i.get('confidence','?')}  source={i.get('source','?')}"
        )
        print(f"    content: {i['content'][:120]}")
        if tags:
            print(f"    tags: {tags}")
        print()


def consolidate(min_confidence: float = 0.5, dry_run: bool = False):
    """Консолидация: группировка связанных инсайтов, повышение статуса."""
    queue = load_queue()
    new_insights = [i for i in queue["insights"] if i["status"] == "new"]

    if not new_insights:
        print("Нет новых инсайтов для консолидации.")
        return

    print(f"Новых инсайтов: {len(new_insights)}")

    # Группировка по тегам и контексту
    groups = {}
    for i in new_insights:
        key_ctx = i.get("context", "")[:30]
        group_key = (i.get("type", "insight"), key_ctx)
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(i)

    promoted = 0
    for (itype, ctx), items in groups.items():
        avg_confidence = sum(i["importance"] for i in items) / len(items)

        if avg_confidence >= min_confidence and len(items) >= 1:
            if not dry_run:
                for i in items:
                    i["status"] = "consolidated"
            promoted += len(items)
            print(
                f"  Группа ({itype}, {ctx!r}): {len(items)} инсайтов, avg_confidence={avg_confidence:.2f} → consolidated"
            )

    if not dry_run:
        save_queue(queue)
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Продвинуто: {promoted} инсайтов")


def show_stats():
    queue = load_queue()
    insights = queue["insights"]
    total = len(insights)

    by_status = {}
    by_type = {}
    by_source = {}
    for i in insights:
        s = i.get("status", "unknown")
        t = i.get("type", "unknown")
        src = i.get("source", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        by_type[t] = by_type.get(t, 0) + 1
        by_source[src] = by_source.get(src, 0) + 1

    print(f"Всего инсайтов: {total}")
    print()
    print("По статусам:")
    for s, c in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")
    print("По типам:")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print("По источникам:")
    for src, c in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {src}: {c}")


def verify_insight(insight_id: str):
    """Подтвердить инсайт (increment confirmations)."""
    queue = load_queue()
    for i in queue["insights"]:
        if i["id"] == insight_id:
            i["confirmations"] = i.get("confirmations", 0) + 1
            i["last_verified"] = datetime.now(timezone.utc).isoformat()
            save_queue(queue)
            print(
                f"✅ Инсайт {insight_id} подтверждён (confirmations={i['confirmations']})"
            )
            return
    print(f"Инсайт {insight_id} не найден")


def main():
    parser = argparse.ArgumentParser(description="Управление инсайтами artifact-pulse")
    subparsers = parser.add_subparsers(dest="command")

    # add
    p_add = subparsers.add_parser("add", help="Добавить инсайт")
    p_add.add_argument("--content", required=True, help="Описание инсайта")
    p_add.add_argument("--source", required=True, help="Источник (имя агента)")
    p_add.add_argument("--type", required=True, dest="insight_type", help="Тип инсайта")
    p_add.add_argument(
        "--confidence", default="medium", choices=list(VALID_CONFIDENCE.keys())
    )
    p_add.add_argument("--context", default="", help="Контекст")
    p_add.add_argument("--tags", default="", help="Теги через запятую")
    p_add.add_argument("--tool", default="", help="Инструмент")

    # list
    p_list = subparsers.add_parser("list", help="Список инсайтов")
    p_list.add_argument("--status", default=None, help="Фильтр по статусу")
    p_list.add_argument("--source", default=None, help="Фильтр по источнику")
    p_list.add_argument("--limit", type=int, default=20)

    # consolidate
    p_cons = subparsers.add_parser("consolidate", help="Консолидация инсайтов")
    p_cons.add_argument("--min-confidence", type=float, default=0.5)
    p_cons.add_argument("--dry-run", action="store_true")

    # stats
    subparsers.add_parser("stats", help="Статистика")

    # verify
    p_verify = subparsers.add_parser("verify", help="Подтвердить инсайт")
    p_verify.add_argument("--id", required=True, help="ID инсайта")

    args = parser.parse_args()

    if args.command == "add":
        add_insight(
            args.content,
            args.source,
            args.insight_type,
            args.confidence,
            args.context,
            args.tags,
            args.tool,
        )
    elif args.command == "list":
        list_insights(args.status, args.limit, args.source)
    elif args.command == "consolidate":
        consolidate(args.min_confidence, args.dry_run)
    elif args.command == "stats":
        show_stats()
    elif args.command == "verify":
        verify_insight(args.id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
