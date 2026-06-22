"""Генерация кода моделью-кодером по готовому нано-промпту.

Кодер сознательно получает минимум — только нано-промпт (в нём постановщик уже
зашил нужные сигнатуры). Так его крошечного окна контекста хватает.
"""

from __future__ import annotations

import re

from ..llm import LLMClient

CODER_SYSTEM = (
    "Ты пишешь код строго по заданию. Выведи ТОЛЬКО итоговое содержимое файла — "
    "без пояснений и без markdown-ограждений."
)

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Убирает markdown-ограждения, если модель всё-таки их добавила."""
    text = text.strip()
    blocks = _FENCE_RE.findall(text)
    if blocks:
        # берём самый длинный фрагмент кода
        return max(blocks, key=len).strip("\n")
    return text


def generate_code(client: LLMClient, nano_prompt: str) -> str:
    raw = client.ask(CODER_SYSTEM, nano_prompt)
    return strip_code_fences(raw)
