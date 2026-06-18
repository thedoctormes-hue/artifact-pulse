"""
test_insights.py — Тесты для artifact_insights.py (M1–M4)

Покрывает:
- CRUD операции (add, list, get)
- Status flow (new → verified → artifact)
- Semantic deduplication
- SQLite хранение
- CLI команды
"""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

# Путь к модулю
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import artifact_insights as ai  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Временная SQLite БД для тестов."""
    db_path = tmp_path / "test_insights.db"

    # Патчим путь к БД
    with patch.object(ai, "DB_PATH", db_path):
        # Инициализируем БД
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
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
                embedding BLOB,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_ins_status ON insights(status);
            CREATE INDEX IF NOT EXISTS idx_ins_type ON insights(type);
            CREATE INDEX IF NOT EXISTS idx_ins_source ON insights(source);
        """)
        conn.commit()
        conn.close()
        yield db_path


@pytest.fixture
def sample_insight():
    """Пример инсайта для тестов."""
    return {
        "id": "INS-TEST-001",
        "timestamp": "2026-06-18T10:00:00+00:00",
        "tool": "test",
        "context": "unit-test",
        "content": "Test insight content about SQL injection in auth module",
        "importance": 0.9,
        "status": "new",
        "confirmations": 0,
        "source": "antcat",
        "type": "finding",
        "confidence": "high",
        "tags": ["test", "security"],
        "session_id": "test-session",
        "agent_pair": "antcat-test",
    }


# ── SQLite CRUD ──────────────────────────────────────────────────────────────


class TestSQLiteCRUD:
    """Тесты SQLite хранения."""

    def test_db_init_creates_table(self, tmp_db):
        """_db_init создаёт таблицу insights."""
        ai._db_init()
        conn = sqlite3.connect(str(tmp_db))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='insights'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1

    def test_save_insight(self, tmp_db, sample_insight):
        """save_insight записывает инсайт в БД."""
        ai.save_insight(sample_insight)
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT * FROM insights WHERE id = ?", ("INS-TEST-001",)
        ).fetchone()
        conn.close()
        assert row is not None

    def test_load_insights_empty(self, tmp_db):
        """load_insights возвращает пустой список для пустой БД."""
        result = ai.load_insights()
        assert result == []

    def test_load_insights_with_data(self, tmp_db, sample_insight):
        """load_insights возвращает сохранённые инсайты."""
        ai.save_insight(sample_insight)
        result = ai.load_insights()
        assert len(result) == 1
        assert result[0]["id"] == "INS-TEST-001"

    def test_load_insights_status_filter(self, tmp_db, sample_insight):
        """load_insights фильтрует по статусу."""
        ai.save_insight(sample_insight)
        new_items = ai.load_insights(status_filter="new")
        assert len(new_items) == 1
        verified_items = ai.load_insights(status_filter="verified")
        assert len(verified_items) == 0

    def test_update_status(self, tmp_db, sample_insight):
        """update_status меняет статус инсайта."""
        ai.save_insight(sample_insight)
        result = ai.update_status("INS-TEST-001", "verified")
        assert result is True
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT status FROM insights WHERE id = ?", ("INS-TEST-001",)
        ).fetchone()
        conn.close()
        assert row[0] == "verified"

    def test_update_status_invalid(self, tmp_db, sample_insight):
        """update_status отвергает невалидный статус."""
        ai.save_insight(sample_insight)
        result = ai.update_status("INS-TEST-001", "invalid_status")
        assert result is False

    def test_update_status_not_found(self, tmp_db):
        """update_status возвращает False для несуществующего ID."""
        result = ai.update_status("INS-NONEXISTENT", "verified")
        assert result is False


# ── Status Flow ──────────────────────────────────────────────────────────────


class TestStatusFlow:
    """Тесты статус-флоу: new → verified → artifact."""

    def test_new_to_verified_via_verify(self, tmp_db, sample_insight):
        """Двойной verify переводит new → verified."""
        ai.save_insight(sample_insight)
        ai.verify_insight("INS-TEST-001")  # conf=1, still new
        ai.verify_insight("INS-TEST-001")  # conf=2, → verified
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT status, confirmations FROM insights WHERE id = ?", ("INS-TEST-001",)
        ).fetchone()
        conn.close()
        assert row[0] == "verified"
        assert row[1] == 2

    def test_promote_verified_to_artifact(self, tmp_db, sample_insight):
        """promote переводит verified → artifact."""
        sample_insight["status"] = "verified"
        ai.save_insight(sample_insight)
        result = ai.promote_insight("INS-TEST-001")
        assert result is True
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT status FROM insights WHERE id = ?", ("INS-TEST-001",)
        ).fetchone()
        conn.close()
        assert row[0] == "artifact"

    def test_promote_new_fails(self, tmp_db, sample_insight):
        """promote НЕ работает для new (только verified)."""
        ai.save_insight(sample_insight)  # status=new
        result = ai.promote_insight("INS-TEST-001")
        assert result is False

    def test_promote_not_found(self, tmp_db):
        """promote возвращает False для несуществующего ID."""
        result = ai.promote_insight("INS-NONEXISTENT")
        assert result is False

    def test_verify_not_found(self, tmp_db):
        """verify обрабатывает несуществующий ID."""
        result = ai.verify_insight("INS-NONEXISTENT")
        assert result is False

    def test_consolidate_new_to_verified(self, tmp_db, sample_insight):
        """consolidate переводит new→verified при confirmations>=2.

        Важно: importance < threshold, иначе уйдёт сразу в artifact.
        """
        sample_insight["confirmations"] = 2
        sample_insight["importance"] = 0.3  # ниже min_confidence=0.5
        ai.save_insight(sample_insight)
        ai.consolidate(min_confidence=0.5)
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT status FROM insights WHERE id = ?", ("INS-TEST-001",)
        ).fetchone()
        conn.close()
        assert row[0] == "verified"

    def test_consolidate_verified_to_artifact(self, tmp_db, sample_insight):
        """consolidate переводит verified→artifact при importance>=threshold."""
        sample_insight["status"] = "verified"
        sample_insight["importance"] = 0.9
        ai.save_insight(sample_insight)
        ai.consolidate(min_confidence=0.5)
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT status FROM insights WHERE id = ?", ("INS-TEST-001",)
        ).fetchone()
        conn.close()
        assert row[0] == "artifact"

    def test_full_status_flow(self, tmp_db, sample_insight):
        """Полный цикл: new → verified → artifact."""
        # 1. Сохраняем как new
        ai.save_insight(sample_insight)

        # 2. Дважды verify → verified
        ai.verify_insight("INS-TEST-001")
        ai.verify_insight("INS-TEST-001")

        # 3. Promote → artifact
        ai.promote_insight("INS-TEST-001")

        # 4. Проверяем
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT status, confirmations FROM insights WHERE id = ?", ("INS-TEST-001",)
        ).fetchone()
        conn.close()
        assert row[0] == "artifact"
        assert row[1] == 2


# ── Semantic Dedup ───────────────────────────────────────────────────────────


class TestSemanticDedup:
    """Тесты семантической дедупликации."""

    def test_cosine_sim_identical(self):
        """Cosine similarity одинаковых векторов = 1.0."""
        vec = [1.0, 2.0, 3.0]
        assert ai._cosine_sim(vec, vec) == pytest.approx(1.0)

    def test_cosine_sim_orthogonal(self):
        """Cosine similarity ортогональных векторов ≈ 0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert ai._cosine_sim(a, b) == pytest.approx(0.0)

    def test_cosine_sim_empty(self):
        """Cosine similarity пустых векторов = 0."""
        assert ai._cosine_sim([], []) == 0.0
        assert ai._cosine_sim([1.0], []) == 0.0

    def test_generate_id_unique(self):
        """generate_id уникален для разных текстов."""
        id1 = ai.generate_id("text A")
        id2 = ai.generate_id("text B")
        assert id1 != id2

    def test_generate_id_format(self):
        """generate_id возвращает формат INS-XXXXXXXXXXXXXX-XXXXXXXX."""
        id_ = ai.generate_id("test")
        assert id_.startswith("INS-")
        assert len(id_.split("-")) == 3


# ── CLI ──────────────────────────────────────────────────────────────────────


class TestCLI:
    """Тесты CLI команд."""

    def test_cli_stats(self, tmp_db, sample_insight, capsys):
        """CLI stats выводит статистику."""
        ai.save_insight(sample_insight)
        # Вызываем напрямую через argparse
        with patch("sys.argv", ["artifact_insights.py", "stats"]):
            ai.main()
        captured = capsys.readouterr()
        assert "Всего инсайтов: 1" in captured.out

    def test_cli_list(self, tmp_db, sample_insight, capsys):
        """CLI list выводит инсайты."""
        ai.save_insight(sample_insight)
        with patch("sys.argv", ["artifact_insights.py", "list", "--limit", "10"]):
            ai.main()
        captured = capsys.readouterr()
        assert "INS-TEST-001" in captured.out

    def test_cli_verify(self, tmp_db, sample_insight, capsys):
        """CLI verify подтверждает инсайт."""
        ai.save_insight(sample_insight)
        with patch(
            "sys.argv", ["artifact_insights.py", "verify", "--id", "INS-TEST-001"]
        ):
            ai.main()
        captured = capsys.readouterr()
        assert "подтверждён" in captured.out

    def test_cli_promote(self, tmp_db, sample_insight, capsys):
        """CLI promote продвигает verified → artifact."""
        sample_insight["status"] = "verified"
        ai.save_insight(sample_insight)
        with patch(
            "sys.argv", ["artifact_insights.py", "promote", "--id", "INS-TEST-001"]
        ):
            ai.main()
        captured = capsys.readouterr()
        assert "artifact" in captured.out


# ── Valid Types / Status ────────────────────────────────────────────────────


class TestValidConstants:
    """Тесты констант валидации."""

    def test_valid_types_include_security(self):
        """VALID_TYPES включает 'security'."""
        assert "security" in ai.VALID_TYPES

    def test_valid_status_flow(self):
        """VALID_STATUS содержит все статусы флоу."""
        assert "new" in ai.VALID_STATUS
        assert "verified" in ai.VALID_STATUS
        assert "artifact" in ai.VALID_STATUS

    def test_valid_confidence_values(self):
        """VALID_CONFIDENCE содержит low/medium/high."""
        assert ai.VALID_CONFIDENCE["low"] == 0.3
        assert ai.VALID_CONFIDENCE["medium"] == 0.6
        assert ai.VALID_CONFIDENCE["high"] == 0.9

    def test_semantic_threshold(self):
        """SEMANTIC_DUP_THRESHOLD = 0.85."""
        assert ai.SEMANTIC_DUP_THRESHOLD == 0.85


# ── Edge Cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Граничные случаи."""

    def test_empty_content_handling(self, tmp_db):
        """Пустой контент не крашит save_insight."""
        insight = {
            "id": "INS-EMPTY",
            "timestamp": "2026-06-18T10:00:00+00:00",
            "content": "",
            "importance": 0.5,
            "source": "test",
            "type": "finding",
        }
        ai.save_insight(insight)
        result = ai.load_insights()
        assert len(result) == 1

    def test_unicode_content(self, tmp_db):
        """Unicode контент сохраняется корректно."""
        insight = {
            "id": "INS-UNICODE",
            "timestamp": "2026-06-18T10:00:00+00:00",
            "content": "Инсайт на русском с эмодзи 🐜",
            "importance": 0.7,
            "source": "antcat",
            "type": "finding",
        }
        ai.save_insight(insight)
        result = ai.load_insights()
        assert result[0]["content"] == "Инсайт на русском с эмодзи 🐜"

    def test_long_content(self, tmp_db):
        """Длинный контент (>1000 символов) сохраняется."""
        insight = {
            "id": "INS-LONG",
            "timestamp": "2026-06-18T10:00:00+00:00",
            "content": "A" * 5000,
            "importance": 0.5,
            "source": "test",
            "type": "finding",
        }
        ai.save_insight(insight)
        result = ai.load_insights()
        assert len(result[0]["content"]) == 5000

    def test_tags_as_list_and_string(self, tmp_db):
        """Tags работают и как list, и как string."""
        # List
        insight1 = {
            "id": "INS-TAGS-1",
            "timestamp": "2026-06-18T10:00:00+00:00",
            "content": "test",
            "importance": 0.5,
            "source": "test",
            "type": "finding",
            "tags": ["tag1", "tag2"],
        }
        ai.save_insight(insight1)

        # String
        insight2 = {
            "id": "INS-TAGS-2",
            "timestamp": "2026-06-18T10:00:00+00:00",
            "content": "test2",
            "importance": 0.5,
            "source": "test",
            "type": "finding",
            "tags": "tag3,tag4",
        }
        ai.save_insight(insight2)

        result = ai.load_insights()
        assert len(result) == 2
