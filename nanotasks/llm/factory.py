"""Фабрика клиентов: по настройкам роли возвращает нужный адаптер.

Провайдеры:
  openai_compatible — Ollama, LM Studio, OpenRouter, VseGPT, BotHub и любой
                      сервис с /v1/chat/completions (задаётся base_url + api_key);
  yandex (alice)    — Алиса / YandexGPT 5.1 Pro (через openai SDK, Responses API);
  gigachat          — Сбер GigaChat-2 / -2-Pro / -2-Max.
"""

from __future__ import annotations

from ..config import ModelConfig
from .base import LLMClient, LLMError
from .gigachat import GigaChatClient
from .openai_compatible import OpenAICompatibleClient
from .yandex import YandexClient


def build_client(cfg: ModelConfig, name: str = "llm") -> LLMClient:
    provider = (cfg.provider or "openai_compatible").lower()
    if provider == "openai_compatible":
        return OpenAICompatibleClient(
            cfg.base_url, cfg.model, cfg.api_key, cfg.temperature, cfg.timeout, name
        )
    if provider in ("yandex", "alice"):
        return YandexClient(cfg, name)
    if provider == "gigachat":
        return GigaChatClient(cfg, name)
    raise LLMError(f"Неизвестный provider '{cfg.provider}' для роли '{name}'.")
