"""Фабрика клиентов: по настройкам роли возвращает нужный адаптер."""

from __future__ import annotations

from ..config import ModelConfig
from .alice import AliceClient
from .base import LLMClient, LLMError
from .gigachat import GigaChatClient
from .openai_compatible import OpenAICompatibleClient


def build_client(cfg: ModelConfig, name: str = "llm") -> LLMClient:
    provider = (cfg.provider or "openai_compatible").lower()
    if provider == "openai_compatible":
        return OpenAICompatibleClient(
            cfg.base_url, cfg.model, cfg.api_key, cfg.temperature, cfg.timeout, name
        )
    if provider == "alice":
        return AliceClient(cfg, name)
    if provider == "gigachat":
        return GigaChatClient(cfg, name)
    raise LLMError(f"Неизвестный provider '{cfg.provider}' для роли '{name}'.")
