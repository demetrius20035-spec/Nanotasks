"""Загрузка YAML-конфигурации."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CANDIDATES = ["config/config.yaml", "config/config.example.yaml"]


@dataclass
class ModelConfig:
    """Настройки одной роли модели (architect / prompt_builder / coder)."""

    provider: str = "openai_compatible"   # openai_compatible | alice | gigachat
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    temperature: float = 0.2
    timeout: int = 600
    extra: dict = field(default_factory=dict)  # провайдер-специфичные поля


@dataclass
class Config:
    database_path: str = "data/nanotasks.duckdb"
    output_dir: str = "output"
    models: dict[str, ModelConfig] = field(default_factory=dict)
    run_mode: str = "review"   # review | auto
    max_retries: int = 1
    variants: int = 1          # кандидатов на пункт при ветвлении (>1 включает выбор)
    cascade_dependents: bool = False   # переоткрывать зависимые пункты при правке
    verify_commands: list[str] = field(default_factory=list)  # компиляция/запуск/тесты
    source_path: str | None = None

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        candidates = [path] if path else DEFAULT_CANDIDATES
        cfg_path = next((p for p in candidates if p and Path(p).exists()), None)
        if cfg_path is None:
            raise FileNotFoundError(
                "Не найден конфиг. Скопируй config/config.example.yaml в config/config.yaml."
            )
        data = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}

        models: dict[str, ModelConfig] = {}
        for role, raw in (data.get("models") or {}).items():
            raw = dict(raw or {})
            models[role] = ModelConfig(
                provider=raw.pop("provider", "openai_compatible"),
                base_url=raw.pop("base_url", None),
                model=raw.pop("model", None),
                api_key=raw.pop("api_key", None),
                temperature=raw.pop("temperature", 0.2),
                timeout=raw.pop("timeout", 600),
                extra=raw,
            )

        run = data.get("run") or {}
        verify = data.get("verify") or {}
        return cls(
            database_path=(data.get("database") or {}).get("path", "data/nanotasks.duckdb"),
            output_dir=(data.get("output") or {}).get("dir", "output"),
            models=models,
            run_mode=run.get("mode", "review"),
            max_retries=int(run.get("max_retries", 1)),
            variants=int(run.get("variants", 1)),
            cascade_dependents=bool(run.get("cascade_dependents", False)),
            verify_commands=list(verify.get("commands") or []),
            source_path=cfg_path,
        )

    def model(self, role: str) -> ModelConfig:
        if role not in self.models:
            raise KeyError(f"В конфиге нет настроек для роли модели '{role}'.")
        return self.models[role]
