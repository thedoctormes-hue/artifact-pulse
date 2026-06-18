#!/usr/bin/env python3
"""
Построение FAISS индекса для семантического поиска по инсайтам.

Использование:
  python3 build_faiss_index.py [--db PATH] [--index PATH] [--rebuild]

Загружает все инсайты из insights.db, генерирует embedding через bge-m3 (Ollama),
строит FAISS IndexFlatIP (Inner Product = cosine similarity для L2-нормализованных векторов).
"""

import argparse
import json
import sqlite3
import time
import urllib.request
from pathlib import Path
import numpy as np

DEFAULT_DB = "/root/LabDoctorM/.qwen/artifacts/insights.db"
DEFAULT_INDEX = "/root/LabDoctorM/.qwen/artifacts/insights.faiss"
OLLAMA_EMBED = "http://127.0.0.1:11434/api/embeddings"
EMBED_MODEL = "bge-m3-cpu"


def get_embedding(text: str, max_retries: int = 3) -> list:
    """Получить embedding из Ollama с retry и rate limiting."""
    import time as _time

    data = json.dumps({"model": EMBED_MODEL, "prompt": text[:512]}).encode()
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                OLLAMA_EMBED, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read()).get("embedding", [])
        except urllib.error.HTTPError as e:
            if e.code == 500 and attempt < max_retries - 1:
                wait = (attempt + 1) * 2
                print(f"    ↻ retry in {wait}s...")
                _time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < max_retries - 1:
                _time.sleep(1)
                continue
            raise


def build_index(db_path: str, index_path: str, rebuild: bool = False):
    """Построить FAISS индекс из инсайтов в БД."""
    import faiss

    # Проверка: индекс уже существует
    if Path(index_path).exists() and not rebuild:
        existing = faiss.read_index(index_path)
        print(f"Индекс уже существует: {existing.ntotal} векторов")
        print("Используйте --rebuild для перестроения")
        return

    # Загрузка инсайтов
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, content, type, source, status FROM insights"
    ).fetchall()
    conn.close()

    print(f"Загружено {len(rows)} инсайтов")

    if not rows:
        print("Нет инсайтов для индексации")
        return

    # Генерация embeddings
    vectors = []
    ids = []
    failed = 0

    t_start = time.time()
    for i, (iid, content, itype, source, status) in enumerate(rows):
        try:
            vec = get_embedding(content)
            if len(vec) != 1024:
                print(f"  ⚠️  {iid}: неожиданная размерность {len(vec)}")
                failed += 1
                continue
            vectors.append(vec)
            ids.append(iid)
        except Exception as e:
            print(f"  ⚠️  {iid}: {e}")
            failed += 1
            continue

        # Прогресс каждые 10
        if (i + 1) % 10 == 0:
            elapsed = time.time() - t_start
            avg = elapsed / (i + 1)
            remaining = avg * (len(rows) - i - 1) / 60
            print(
                f"  {i+1}/{len(rows)} ({avg:.1f}s/embedding, ~{remaining:.1f}min left)"
            )

    if not vectors:
        print("❌ Ни один embedding не сгенерирован")
        return

    t_total = time.time() - t_start
    print(
        f"\nEmbeddings: {len(vectors)} за {t_total:.1f}s ({t_total/len(vectors):.1f}s avg)"
    )
    if failed:
        print(f"  Пропущено: {failed}")

    # Создание FAISS индекса
    vectors_np = np.array(vectors, dtype=np.float32)

    # L2-нормализация (Inner Product = Cosine Similarity)
    faiss.normalize_L2(vectors_np)

    # IndexFlatIP — точный поиск через Inner Product
    dim = vectors_np.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors_np)

    # Сохранение индекса
    faiss.write_index(index, index_path)

    # Сохранение маппинга id → индекс
    id_map_path = index_path + ".ids.json"
    with open(id_map_path, "w") as f:
        json.dump(ids, f)

    index_size = Path(index_path).stat().st_size / 1024
    map_size = Path(id_map_path).stat().st_size / 1024

    print("\n✅ FAISS индекс сохранён:")
    print(f"  Индекс: {index_path} ({index_size:.1f} KB)")
    print(f"  ID map: {id_map_path} ({map_size:.1f} KB)")
    print(f"  Векторов: {index.ntotal}, размерность: {dim}")

    # Quick self-test
    print("\n🧪 Self-test...")
    query_vec = vectors_np[:1].copy()
    distances, indices = index.search(query_vec, 3)
    print(f"  Запрос: {ids[0][:30]}...")
    print("  Top-3 совпадения:")
    for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
        print(f"    {rank+1}. {ids[idx][:30]}... (cosine={dist:.4f})")


def search_index(index_path: str, query: str, top_k: int = 5):
    """Поиск похожих инсайтов по тексту."""
    import faiss

    index = faiss.read_index(index_path)
    with open(index_path + ".ids.json") as f:
        ids = json.load(f)

    vec = np.array([get_embedding(query)], dtype=np.float32)
    faiss.normalize_L2(vec)

    distances, indices = index.search(vec, top_k)
    return [(ids[idx], float(dist)) for dist, idx in zip(distances[0], indices[0])]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FAISS индекс для инсайтов")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--search", type=str, help="Поиск по тексту")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    if args.search:
        results = search_index(args.index, args.search, args.top_k)
        print(f"Поиск: '{args.search[:80]}...'")
        for rank, (iid, score) in enumerate(results):
            print(f"  {rank+1}. {iid} (cosine={score:.4f})")
    else:
        build_index(args.db, args.index, args.rebuild)
