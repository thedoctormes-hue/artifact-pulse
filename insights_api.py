#!/usr/bin/env python3
"""
insights_api.py — FastAPI REST API для системы инсайтов artifact-pulse.

Эндпоинты:
  POST   /insights              — добавить инсайт
  GET    /insights              — список инсайтов (фильтры: status, source, type, limit)
  GET    /insights/{id}         — получить инсайт по ID
  POST   /insights/{id}/verify  — подтвердить инсайт
  POST   /insights/{id}/promote — продвинуть verified → artifact
  POST   /insights/consolidate  — консолидация new → verified → artifact
  GET    /insights/stats        — статистика
  GET    /health                — health check

Запуск:
  uvicorn insights_api:app --host 0.0.0.0 --port 8720 --workers 1
"""

import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# ── Импорт ядра ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from artifact_insights import (
    add_insight,
    load_insights,
    verify_insight,
    promote_insight,
    consolidate,
    _db_init,
    _get_db,
    VALID_TYPES,
    VALID_CONFIDENCE,
)

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Artifact Pulse — Insights API",
    version="2.0.0",
    description="REST API для управления инсайтами лаборатории",
)


class InsightCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4096, description="Текст инсайта")
    source: str = Field(..., min_length=1, max_length=64, description="Источник (имя агента)")
    type: str = Field(..., description="Тип: finding, error, decision, pattern, anti-pattern, insight, security")
    confidence: str = Field(default="medium", description="Уверенность: low, medium, high")
    context: str = Field(default="", max_length=1024, description="Контекст")
    tags: str = Field(default="", description="Теги через запятую")
    tool: str = Field(default="", description="Инструмент")
    session_id: str = Field(default="", description="ID сессии")
    agent_pair: str = Field(default="", description="Пара агентов")


class InsightResponse(BaseModel):
    id: str
    content: str
    source: str
    type: str
    confidence: str
    status: str
    importance: float
    confirmations: int
    tags: list[str] = []
    session_id: str = ""
    agent_pair: str = ""
    timestamp: str = ""


class StatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    by_source: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    version: str
    db_path: str


# ── Эндпоинты ─────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check."""
    from artifact_insights import DB_PATH
    _db_init()
    return HealthResponse(
        status="ok",
        version="2.0.0",
        db_path=str(DB_PATH),
    )


@app.post("/insights", response_model=InsightResponse, status_code=201)
async def create_insight(body: InsightCreate):
    """Добавить новый инсайт. Семантические дубликаты отклоняются."""
    # Validate type and confidence early to give clear 422
    if body.type not in VALID_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid type '{body.type}'. Valid types: {sorted(VALID_TYPES)}",
        )
    if body.confidence not in VALID_CONFIDENCE:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid confidence '{body.confidence}'. Valid: {list(VALID_CONFIDENCE.keys())}",
        )

    try:
        result = add_insight(
            content=body.content,
            source=body.source,
            insight_type=body.type,
            confidence=body.confidence,
            context=body.context,
            tags=body.tags,
            tool=body.tool,
            session_id=body.session_id,
            agent_pair=body.agent_pair,
        )
    except ValueError as e:
        # Raised by add_insight for semantic duplicate or other validation
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        # Any other unexpected error
        raise HTTPException(status_code=500, detail=str(e))

    if not result:
        raise HTTPException(
            status_code=409,
            detail="Semantic duplicate: insight already exists",
        )
    return InsightResponse(**result)


@app.get("/insights")
async def list_insights_endpoint(
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    source: Optional[str] = Query(None, description="Фильтр по источнику"),
    type: Optional[str] = Query(None, description="Фильтр по типу"),
    limit: int = Query(20, ge=1, le=500),
):
    """Список инсайтов с фильтрацией."""
    insights = load_insights(status_filter=status, limit=limit)
    if source:
        insights = [i for i in insights if i.get("source") == source]
    if type:
        insights = [i for i in insights if i.get("type") == type]
    return {"total": len(insights), "insights": insights}


@app.get("/insights/stats", response_model=StatsResponse)
async def stats_endpoint():
    """Статистика по инсайтам."""
    _db_init()
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM insights GROUP BY status"
    ).fetchall())
    by_type = dict(conn.execute(
        "SELECT type, COUNT(*) FROM insights GROUP BY type"
    ).fetchall())
    by_source = dict(conn.execute(
        "SELECT source, COUNT(*) FROM insights GROUP BY source"
    ).fetchall())
    conn.close()
    return StatsResponse(
        total=total,
        by_status=by_status,
        by_type=by_type,
        by_source=by_source,
    )


@app.get("/insights/{insight_id}")
async def get_insight(insight_id: str):
    """Получить инсайт по ID."""
    insights = load_insights(limit=500)
    for i in insights:
        if i.get("id") == insight_id:
            return i
    raise HTTPException(status_code=404, detail=f"Insight {insight_id} not found")


@app.post("/insights/{insight_id}/verify")
async def verify_insight_endpoint(insight_id: str):
    """Подтвердить инсайт (increment confirmations, new → verified)."""
    try:
        ok = verify_insight(insight_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"Insight {insight_id} not found")
    return {"status": "ok", "id": insight_id}


@app.post("/insights/{insight_id}/promote")
async def promote_insight_endpoint(insight_id: str):
    """Продвинуть инсайт verified → artifact."""
    try:
        ok = promote_insight(insight_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(
            status_code=0,
            detail=f"Insight {insight_id} not found or not in 'verified' status",
        )
    return {"status": "ok", "id": insight_id, "new_status": "artifact"}


@app.post("/insights/consolidate")
async def consolidate_endpoint(min_confidence: float = 0.5):
    """Запустить консолидацию: new → verified → artifact."""
    consolidate(min_confidence=min_confidence)
    return {"status": "ok"}


# ── CLI fallback (if run directly) ───────────────────────────────────────────

if __name__ == "__main__":
    # This allows running `python insights_api.py` for debugging
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8720)