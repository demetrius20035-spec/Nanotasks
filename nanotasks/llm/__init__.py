"""Адаптеры к моделям. Единый интерфейс :class:`LLMClient` для всех провайдеров."""

from .base import LLMClient, LLMError, LLMResponse, Message
from .factory import build_client

__all__ = ["LLMClient", "LLMError", "LLMResponse", "Message", "build_client"]
