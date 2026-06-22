"""Генерация кода моделью-кодером по готовому нано-промпту.

Кодер сознательно получает минимум — только нано-промпт (в нём постановщик уже
зашил нужные сигнатуры). Так его крошечного окна контекста хватает.
"""

from __future__ import annotations

from ..llm import LLMClient
from ..textutil import strip_code_fences

CODER_SYSTEM = (
    "Ты пишешь код строго по заданию. Выведи ТОЛЬКО итоговое содержимое файла — "
    "без пояснений и без markdown-ограждений."
)

__all__ = ["CODER_SYSTEM", "generate_code", "strip_code_fences"]


def generate_code(client: LLMClient, nano_prompt: str) -> str:
    raw = client.ask(CODER_SYSTEM, nano_prompt)
    return strip_code_fences(raw)
