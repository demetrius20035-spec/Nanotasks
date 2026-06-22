"""Клиент для OpenAI-совместимого API.

Покрывает локальные модели:
  • Ollama     — base_url: http://localhost:11434/v1
  • LM Studio  — base_url: http://localhost:1234/v1
а также любой облачный сервис с тем же протоколом (через api_key).
"""

from __future__ import annotations

import httpx

from .base import LLMClient, LLMError, LLMResponse, Message


class OpenAICompatibleClient(LLMClient):
    def __init__(self, base_url, model, api_key=None, temperature=0.2,
                 timeout=600, name="local"):
        if not base_url or not model:
            raise LLMError(f"Роль '{name}': в конфиге не заданы base_url и/или model.")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.name = name

    def complete(self, messages: list[Message], temperature: float | None = None) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"[{self.name}] ошибка запроса к {url}: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"[{self.name}] неожиданный формат ответа: {data!r}") from exc
        return LLMResponse(content=content, model=self.model, raw=data)
