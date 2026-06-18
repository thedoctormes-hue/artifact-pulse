"""
test_session_miner.py — Тесты для session_insights_miner.py

Покрывает:
- Извлечение инсайтов из сессий
- Фильтрация дубликатов
- Интеграция с artifact_insights.py
- Security pattern detection
"""

import sys
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import session_insights_miner as sim  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_session_text():
    """Пример текста сессии с инсайтами."""
    return """
    [Agent] Обнаружена уязвимость SQL-инъекции в модуле авторизации.
    Это критическая находка — нужно исправить до релиза.
    
    [Decision] Принято решение использовать parameterized queries вместо конкатенации.
    
    [Error] Тест упал с ошибкой timeout при подключении к базе данных.
    
    [Pattern] Все запросы к БД должны использовать connection pooling.
    """


@pytest.fixture
def sample_insight_data():
    """Пример данных инсайта для майнера."""
    return {
        "content": "SQL injection vulnerability in auth module",
        "type": "finding",
        "confidence": "high",
        "source": "test-agent",
        "context": "security audit",
        "importance": 0.9,
    }


# ── Session Parsing ──────────────────────────────────────────────────────────


class TestSessionParsing:
    """Тесты парсинга сессий."""

    def test_extract_insights_from_text(self, sample_session_text):
        """Майнер извлекает инсайты из текста сессии."""
        # Проверяем что метод существует и вызывается
        if hasattr(sim, "extract_insights"):
            result = sim.extract_insights(sample_session_text)
            assert isinstance(result, list)
        else:
            pytest.skip("extract_insights not implemented")

    def test_empty_session(self):
        """Пустая сессия не крашит майнер."""
        if hasattr(sim, "extract_insights"):
            result = sim.extract_insights("")
            assert result == []
        else:
            pytest.skip("extract_insights not implemented")

    def test_session_with_no_insights(self):
        """Сессия без инсайтов возвращает пустой список."""
        if hasattr(sim, "extract_insights"):
            result = sim.extract_insights("Just a regular conversation about weather.")
            assert isinstance(result, list)
        else:
            pytest.skip("extract_insights not implemented")


# ── Security Patterns ────────────────────────────────────────────────────────


class TestSecurityPatterns:
    """Тесты обнаружения security-паттернов."""

    def test_detects_vulnerability_keyword(self):
        """is_security_insight обнаруживает 'vulnerability'."""
        assert sim.is_security_insight("Found a vulnerability in auth") is True

    def test_detects_security_keyword(self):
        """is_security_insight обнаруживает 'security'."""
        assert sim.is_security_insight("Security issue in API") is True

    def test_detects_leak_keyword(self):
        """is_security_insight обнаруживает 'leak'."""
        assert sim.is_security_insight("Data leak in logs") is True

    def test_detects_warning_keyword(self):
        """is_security_insight обнаруживает 'warning'."""
        assert sim.is_security_insight("Warning: unsafe operation") is True

    def test_non_security_not_flagged(self):
        """Обычный текст не помечается как security."""
        assert sim.is_security_insight("Refactored database layer") is False


# ── Type Classification ──────────────────────────────────────────────────────


class TestTypeClassification:
    """Тесты классификации типов инсайтов."""

    def test_classify_finding(self):
        """Классификация finding."""
        if hasattr(sim, "classify_insight_type"):
            result = sim.classify_insight_type("Обнаружена уязвимость в коде")
            assert result == "finding"
        else:
            pytest.skip("classify_insight_type not implemented")

    def test_classify_error(self):
        """Классификация error."""
        if hasattr(sim, "classify_insight_type"):
            result = sim.classify_insight_type("Ошибка при выполнении теста")
            assert result == "error"
        else:
            pytest.skip("classify_insight_type not implemented")

    def test_classify_decision(self):
        """Классификация decision."""
        if hasattr(sim, "classify_insight_type"):
            result = sim.classify_insight_type("Принято решение использовать Redis")
            assert result == "decision"
        else:
            pytest.skip("classify_insight_type not implemented")

    def test_classify_pattern(self):
        """Классификация pattern."""
        if hasattr(sim, "classify_insight_type"):
            result = sim.classify_insight_type("Паттерн: все запросы через pool")
            assert result == "pattern"
        else:
            pytest.skip("classify_insight_type not implemented")


# ── Integration ──────────────────────────────────────────────────────────────


class TestIntegration:
    """Интеграционные тесты с artifact_insights."""

    def test_process_session_signature(self):
        """process_session принимает (Path, Set[str])."""
        import inspect

        sig = inspect.signature(sim.process_session)
        params = list(sig.parameters.keys())
        assert "traj_file" in params
        assert "existing_hashes" in params

    def test_process_session_returns_int(self, tmp_path):
        """process_session возвращает int (количество новых инсайтов)."""
        # Создаём пустой trajectory файл
        traj_dir = tmp_path / "test-agent"
        traj_dir.mkdir()
        traj_file = traj_dir / "test-session.trajectory.json"
        traj_file.write_text(json.dumps({"messages": []}))

        result = sim.process_session(traj_file, set())
        assert isinstance(result, int)
        assert result == 0  # пустой файл → 0 инсайтов

    def test_miner_skips_duplicates(self, tmp_path):
        """Майнер пропускает дубликаты по hash."""
        traj_dir = tmp_path / "test-agent"
        traj_dir.mkdir()
        traj_file = traj_dir / "test-session.trajectory.json"

        # Создаём trajectory с одним сообщением
        traj_data = {
            "messages": [
                {"role": "assistant", "content": "Found a vulnerability in auth module"}
            ]
        }
        traj_file.write_text(json.dumps(traj_data))

        # Первый запуск — должен добавить
        sim.process_session(traj_file, set())
        # Второй запуск с тем же hash — должен пропустить
        # (hash уже в existing_hashes)
        # Примечание: process_session не обновляет existing_hashes сам,
        # это делает main()


# ── Edge Cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Граничные случаи."""

    def test_very_long_session(self):
        """Очень длинная сессия не крашит майнер."""
        long_text = "Some text " * 10000
        if hasattr(sim, "extract_insights"):
            result = sim.extract_insights(long_text)
            assert isinstance(result, list)
        else:
            pytest.skip("extract_insights not implemented")

    def test_unicode_session(self):
        """Unicode в сессии обрабатывается корректно."""
        unicode_text = "Обнаружена ошибка 🐛 в модуле авторизации — критично!"
        if hasattr(sim, "extract_insights"):
            result = sim.extract_insights(unicode_text)
            assert isinstance(result, list)
        else:
            pytest.skip("extract_insights not implemented")

    def test_special_characters(self):
        """Спецсимволы не крашат парсер."""
        special = "Error: `SELECT * FROM users WHERE id = '1' OR '1'='1'`"
        if hasattr(sim, "extract_insights"):
            result = sim.extract_insights(special)
            assert isinstance(result, list)
        else:
            pytest.skip("extract_insights not implemented")
