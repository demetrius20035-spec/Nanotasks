"""Адаптер Сбер ГигаЧат (GigaChat-2 / -2-Pro / -2-Max).

По примеру пользователя — OAuth за access_token, затем chat/completions:

    # авторизация
    POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth
      headers: Content-Type=x-www-form-urlencoded, Accept=json,
               RqUID=<uuid>, Authorization=Basic <TOKEN>
      data: scope=<SCOPE>                       → { "access_token": ... }
    # генерация
    POST https://gigachat.devices.sberbank.ru/api/v1/chat/completions
      headers: Authorization=Bearer <access_token>
      body: { "model": "GigaChat-2", "messages": [...], "profanity_check": true }

Конфиг роли:
    provider: gigachat
    model: GigaChat-2                # GigaChat-2-Pro | GigaChat-2-Max
    api_key: <Authorization key (Basic TOKEN)>
    scope: GIGACHAT_API_PERS         # extra
    verify_ssl: false                # extra — часто нужно из-за российского УЦ
    profanity_check: false           # extra (необязательно)
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
        self.model = cfg.model or "GigaChat-2"
        self.auth_key = cfg.api_key
        self.scope = cfg.extra.get("scope", "GIGACHAT_API_PERS")
        self.verify = bool(cfg.extra.get("verify_ssl", True))
        self.profanity_check = cfg.extra.get("profanity_check")
        self.temperature = cfg.temperature
        self.timeout = cfg.timeout
        self._token: str | None = None
        self._token_exp = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        if not self.auth_key:
            raise LLMError(f"[{self.name}] нужен api_key (Authorization key) в секции роли.")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {self.auth_key}",
        }
        try:
            with httpx.Client(timeout=self.timeout, verify=self.verify) as client:
                resp = client.post(OAUTH_URL, data={"scope": self.scope}, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"[{self.name}] ошибка OAuth: {exc}") from exc
        self._token = data["access_token"]
        self._token_exp = time.time() + 1500  # ~25 минут с запасом
        return self._token

    def complete(self, messages: list[Message], temperature: float | None = None) -> LLMResponse:
        token = self._access_token()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
        }
        if self.profanity_check is not None:
            payload["profanity_check"] = bool(self.profanity_check)
        try:
            with httpx.Client(timeout=self.timeout, verify=self.verify) as client:
                resp = client.post(CHAT_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"[{self.name}] ошибка запроса: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"[{self.name}] неожиданный ответ: {data!r}") from exc
        return LLMResponse(content=content, model=self.model, raw=data)
