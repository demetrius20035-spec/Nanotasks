"""Адаптер YandexGPT («Алиса» / Yandex Foundation Models).

СКЕЛЕТ — сверь с актуальным примером и при необходимости поправь. Поля конфига:

    architect:
      provider: alice
      model: yandexgpt          # или yandexgpt-lite
      api_key: <API-ключ сервисного аккаунта>
      folder_id: <идентификатор каталога>     # пойдёт в extra
"""

from __future__ import annotations

import httpx

from ..config import ModelConfig
from .base import LLMClient, LLMError, LLMResponse, Message

DEFAULT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class AliceClient(LLMClient):
    def __init__(self, cfg: ModelConfig, name: str = "alice"):
        self.name = name
        self.model = cfg.model or "yandexgpt"
        self.api_key = cfg.api_key
        self.url = cfg.base_url or DEFAULT_URL
        self.temperature = cfg.temperature
        self.timeout = cfg.timeout
        self.folder_id = cfg.extra.get("folder_id")
        self.max_tokens = int(cfg.extra.get("max_tokens", 2000))

    def complete(self, messages: list[Message], temperature: float | None = None) -> LLMResponse:
        if not self.api_key or not self.folder_id:
            raise LLMError("[alice] нужны api_key и folder_id в секции роли конфига.")
        payload = {
            "modelUri": f"gpt://{self.folder_id}/{self.model}",
            "completionOptions": {
                "stream": False,
                "temperature": self.temperature if temperature is None else temperature,
                "maxTokens": self.max_tokens,
            },
            "messages": [{"role": m.role, "text": m.content} for m in messages],
        }
        headers = {"Authorization": f"Api-Key {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"[alice] ошибка запроса: {exc}") from exc
        try:
            content = data["result"]["alternatives"][0]["message"]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"[alice] неожиданный ответ: {data!r}") from exc
        return LLMResponse(content=content, model=self.model, raw=data)
