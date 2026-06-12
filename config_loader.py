"""Общий загрузчик конфигурации для всех модулей Artifact Pulse."""

import yaml
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "artifact_dirs.yaml"

def load_config():
    """Загружает конфиг из YAML. Возвращает dict с lab_dir, artifact_dirs, state_files."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f)
    return {"lab_dir": "/root/LabDoctorM", "artifact_dirs": {}, "state_files": {}}

def get_lab_dir():
    """Возвращает Path к корню лаборатории."""
    cfg = load_config()
    return Path(cfg.get("lab_dir", "/root/LabDoctorM"))

def get_artifact_dirs():
    """Возвращает dict {type: Path} для всех папок артефактов."""
    cfg = load_config()
    lab = Path(cfg.get("lab_dir", "/root/LabDoctorM"))
    dirs = cfg.get("artifact_dirs", {})
    if dirs:
        return {k: lab / v for k, v in dirs.items()}
    return {
        "pattern": lab / "patterns",
        "adr": lab / "adr",
        "rule": lab / "rules",
        "spec": lab / "specs",
        "incident": lab / "incidents",
        "metric": lab / "metrics",
    }

def get_state_file(key):
    """Возвращает Path к файлу состояния по ключу из state_files."""
    cfg = load_config()
    lab = Path(cfg.get("lab_dir", "/root/LabDoctorM"))
    defaults = {
        "insights_queue": ".qwen/artifacts/insights_queue.json",
        "search_index": ".qwen/artifacts/search_index.json",
        "artifact_stats": ".qwen/artifacts/artifact_stats.json",
        "health_history": ".qwen/artifacts/health_history.jsonl",
        "alerts": ".qwen/artifacts/alerts.json",
        "trends": ".qwen/artifacts/trends.json",
        "changelog": "ARTIFACT_CHANGELOG.md",
    }
    state_files = cfg.get("state_files", {})
    path_str = state_files.get(key, defaults.get(key, ""))
    return lab / path_str if path_str else None
