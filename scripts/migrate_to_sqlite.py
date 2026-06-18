#!/usr/bin/env python3
"""
Миграция insights_queue.json → SQLite.

SQLite обеспечивает:
- Атомарные транзакции (нет race condition)
- Индексы по status, type, source (быстрый поиск)
- FTS5 для полнотекстового поиска по content
- Меньше размер на диске (нет дублирования ключей)
- Потокобезопасность (WAL mode)

Использование:
  python3 migrate_to_sqlite.py [--json PATH] [--db PATH] [--verify] [--keep-json]
"""

import argparse
import json
import sqlite3
import sys
import os
from datetime import datetime, timezone

DEFAULT_JSON = "/root/LabDoctorM/.qwen/artifacts/insights_queue.json"
DEFAULT_DB = "/root/LabDoctorM/.qwen/artifacts/insights.db"


def create_schema(conn: sqlite3.Connection):
    """Создать схему SQLite с индексами и FTS5."""
    conn.executescript("""
        -- Основная таблица инсайтов
        CREATE TABLE IF NOT EXISTS insights (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            tool TEXT DEFAULT 'manual',
            context TEXT DEFAULT '',
            content TEXT NOT NULL,
            importance REAL DEFAULT 0.6,
            status TEXT DEFAULT 'new',
            confirmations INTEGER DEFAULT 0,
            source TEXT NOT NULL,
            type TEXT NOT NULL,
            confidence TEXT DEFAULT 'medium',
            tags TEXT DEFAULT '',
            session_id TEXT DEFAULT '',
            agent_pair TEXT DEFAULT '',
            embedding BLOB,           -- сериализованный embedding vector
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Индексы
        CREATE INDEX IF NOT EXISTS idx_status ON insights(status);
        CREATE INDEX IF NOT EXISTS idx_type ON insights(type);
        CREATE INDEX IF NOT EXISTS idx_source ON insights(source);
        CREATE INDEX IF NOT EXISTS idx_timestamp ON insights(timestamp);
        CREATE INDEX IF NOT EXISTS idx_confirmations ON insights(confirmations);

        -- FTS5 для полнотекстового поиска
        CREATE VIRTUAL TABLE IF NOT EXISTS insights_fts USING fts5(
            content, 
            type, 
            source, 
            tags,
            content=insights,
            content_rowid=rowid
        );

        -- Триггеры для синхронизации FTS
        CREATE TRIGGER IF NOT EXISTS insights_ai AFTER INSERT ON insights BEGIN
            INSERT INTO insights_fts(rowid, content, type, source, tags) 
            VALUES (new.rowid, new.content, new.type, new.source, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS insights_ad AFTER DELETE ON insights BEGIN
            INSERT INTO insights_fts(insights_fts, rowid, content, type, source, tags) 
            VALUES ('delete', old.rowid, old.content, old.type, old.source, old.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS insights_au AFTER UPDATE ON insights BEGIN
            INSERT INTO insights_fts(insights_fts, rowid, content, type, source, tags) 
            VALUES ('delete', old.rowid, old.content, old.type, old.source, old.tags);
            INSERT INTO insights_fts(rowid, content, type, source, tags) 
            VALUES (new.rowid, new.content, new.type, new.source, new.tags);
        END;

        -- Таблица для отслеживания миграций
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- WAL mode для параллельного чтения
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
    """)


def migrate_json_to_sqlite(json_path: str, db_path: str, verify: bool = False) -> dict:
    """Мигрировать данные из JSON в SQLite. Возвращает статистику."""
    stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    # Загрузка JSON
    with open(json_path, "r", encoding="utf-8") as f:
        queue = json.load(f)

    insights = queue.get("insights", [])
    stats["total"] = len(insights)

    # Подключение к SQLite
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    create_schema(conn)

    # Проверка: уже мигрировали?
    existing = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
    if existing > 0:
        print(f"⚠️  В SQLite уже есть {existing} записей. Пропускаем дубликаты.")

    # Миграция
    for item in insights:
        try:
            # Проверка дубликата по ID
            row = conn.execute(
                "SELECT id FROM insights WHERE id=?", (item["id"],)
            ).fetchone()
            if row:
                stats["skipped"] += 1
                continue

            # Сериализация embedding если есть
            embedding_blob = None
            if "embedding" in item and item["embedding"]:
                import struct

                embedding_blob = struct.pack(
                    f"{len(item['embedding'])}f", *item["embedding"]
                )

            tags = item.get("tags", [])
            if isinstance(tags, list):
                tags = ",".join(tags)

            conn.execute(
                """
                INSERT INTO insights (
                    id, timestamp, tool, context, content, importance,
                    status, confirmations, source, type, confidence,
                    tags, session_id, agent_pair, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    item["id"],
                    item.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    item.get("tool", "manual"),
                    item.get("context", ""),
                    item["content"],
                    item.get("importance", 0.6),
                    item.get("status", "new"),
                    item.get("confirmations", 0),
                    item["source"],
                    item["type"],
                    item.get("confidence", "medium"),
                    tags,
                    item.get("session_id", ""),
                    item.get("agent_pair", ""),
                    embedding_blob,
                ),
            )
            stats["migrated"] += 1

        except Exception as e:
            print(f"  ⚠️  Error migrating {item.get('id', '?')}: {e}", file=sys.stderr)
            stats["errors"] += 1

    # Сохраняем метаданные миграции
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("migrated_at", datetime.now(timezone.utc).isoformat()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("source_json", json_path),
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("total_migrated", str(stats["migrated"])),
    )

    conn.commit()

    # Верификация
    if verify:
        sqlite_count = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
        json_count = len(insights)
        print("\n📊 Верификация:")
        print(f"  JSON records:  {json_count}")
        print(f"  SQLite records: {sqlite_count}")
        print(
            f"  Migrated: {stats['migrated']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}"
        )

        if sqlite_count != json_count:
            print("  ⚠️  Расхождение! Возможно дубликаты в JSON.")
        else:
            print("  ✅ Количество записей совпадает.")

    # Размер файла
    db_size = os.path.getsize(db_path)
    json_size = os.path.getsize(json_path)
    print("\n💾 Размер на диске:")
    print(f"  JSON:   {json_size / 1024:.1f} KB")
    print(f"  SQLite: {db_size / 1024:.1f} KB")
    print(f"  Экономия: {(1 - db_size / json_size) * 100:.0f}%")

    conn.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Миграция инсайтов JSON → SQLite")
    parser.add_argument("--json", default=DEFAULT_JSON, help="Путь к JSON файлу")
    parser.add_argument("--db", default=DEFAULT_DB, help="Путь к SQLite базе")
    parser.add_argument("--verify", action="store_true", help="Верификация миграции")
    parser.add_argument(
        "--keep-json", action="store_true", help="Не удалять JSON после миграции"
    )
    args = parser.parse_args()

    if not os.path.exists(args.json):
        print(f"❌ JSON файл не найден: {args.json}")
        sys.exit(1)

    print(f"🚀 Миграция: {args.json} → {args.db}")
    stats = migrate_json_to_sqlite(args.json, args.db, args.verify)

    if stats["errors"] == 0 and not args.keep_json:
        backup = args.json + ".bak"
        os.rename(args.json, backup)
        print(f"\n📦 JSON перемещён в бэкап: {backup}")

    print(f"\n✅ Миграция завершена: {stats['migrated']} записей")


if __name__ == "__main__":
    main()
