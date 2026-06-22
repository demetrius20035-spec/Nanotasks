"""Адаптер Сбер ГигаЧат.

СКЕЛЕТ — сверь с актуальным примером и при необходимости поправь. Поля конфига:

    architect:
      provider: gigachat
      model: GigaChat                 # GigaChat-Pro и т.п.
      api_key: <Authorization key (base64 от client_id:secret)>
      scope: GIGACHAT_API_PERS        # пойдёт в extra
      verify_ssl: false               # часто требуется из-за российского УЦ

Поток: OAuth (access_token живёт ~30 мин) → chat/completions (OpenAI-подобный).
"""

from __future__ import annotations

import time
import uuid

import httpx

from ..config import ModelConfig
from .base import LLMClient, LLMError, LLMResponse, Message

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


class GigaChatClient(LLMClient):
    def __init__(self, cfg: ModelConfig, name: str = "gigachat"):
        self.name = name
        self.model = cfg.model or "GigaChat"
        self.auth_key = cfg.api_key
        self.scope = cfg.extra.get("scope", "GIGACHAT_API_PERS")
        self.verify = bool(cfg.extra.get("verify_ssl", True))
        self.temperature = cfg.temperature
        self.timeout = cfg.timeout
        self._token: str | None = None
        self._token_exp = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        if not self.auth_key:
            raise LLMError("[gigachat] нужен api_key (Authorization key) в секции роли.")
        headers = {
            "Authorization": f"Basic {self.auth_key}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            with httpx.Client(timeout=self.timeout, verify=self.verify) as client:
                resp = client.post(OAUTH_URL, data={"scope": self.scope}, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"[gigachat] ошибка OAuth: {exc}") from exc
        self._token = data["access_token"]
        self._token_exp = time.time() + 1500  # ~25 минут, с запасом
        return self._token

    def complete(self, messages: list[Message], temperature: float | None = None) -> LLMResponse:
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
        }
        try:
            with httpx.Client(timeout=self.timeout, verify=self.verify) as client:
                resp = client.post(CHAT_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"[gigachat] ошибка запроса: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"[gigachat] неожиданный ответ: {data!r}") from exc
        return LLMResponse(content=content, model=self.model, raw=data)
