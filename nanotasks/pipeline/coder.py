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

__all__ = ["CODER_SYSTEM", "generate_code", "generate_variants", "variant_temperatures",
           "strip_code_fences"]


def generate_code(client: LLMClient, nano_prompt: str,
                  temperature: float | None = None) -> str:
    raw = client.ask(CODER_SYSTEM, nano_prompt, temperature=temperature)
    return strip_code_fences(raw)


def variant_temperatures(n: int, base: float = 0.2, step: float = 0.3) -> list[float]:
    """Температуры для n кандидатов: растущий разброс (для разнообразия), ≤ 1.0."""
    return [round(min(base + step * i, 1.0), 2) for i in range(max(1, n))]


def generate_variants(client: LLMClient, nano_prompt: str, n: int = 2,
                      temperatures: list[float] | None = None) -> list[str]:
    """n кандидатов по одному и тому же нано-промпту, с разными температурами.

    Идея best-of-N: маленький кодер ненадёжен, поэтому дешевле сгенерировать
    несколько вариантов и затем выбрать лучший (человеком или моделью-судьёй).
    """
    temps = temperatures or variant_temperatures(n)
    return [generate_code(client, nano_prompt, t) for t in temps[:max(1, n)]]
