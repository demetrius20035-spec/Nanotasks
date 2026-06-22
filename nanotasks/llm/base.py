"""Базовый интерфейс клиента модели.

Любой провайдер (локальный OpenAI-совместимый, Алиса, ГигаЧат) реализует
один метод `complete`. Остальная система не знает, что под капотом.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    role: str       # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    raw: dict | None = None


class LLMError(RuntimeError):
    """Любая ошибка обращения к модели."""


class LLMClient(ABC):
    name: str = "llm"
    model: str = ""

    @abstractmethod
    def complete(self, messages: list[Message], temperature: float | None = None) -> LLMResponse:
        ...

    def ask(self, system: str, user: str, temperature: float | None = None) -> str:
        """Удобный шорткат: system + user → текст ответа."""
        messages: list[Message] = []
        if system:
            messages.append(Message("system", system))
        messages.append(Message("user", user))
        return self.complete(messages, temperature=temperature).content
