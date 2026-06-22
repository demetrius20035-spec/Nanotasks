"""Выбор лучшего кандидата большой моделью-судьёй (LLM-as-judge).

Когда для пункта сгенерировано несколько вариантов (см. ветвление в кодере),
судья сравнивает их и указывает индекс лучшего с коротким обоснованием.
Это advisory-шаг: финальное слово всё равно за человеком (select_variant).
"""

from __future__ import annotations

import re

from ..llm import LLMClient
from ..models import Task

JUDGE_SYSTEM = (
    "Ты — придирчивый ревьюер кода. Тебе дают несколько вариантов реализации "
    "ОДНОГО пункта задания. Выбери единственный лучший по корректности, полноте и "
    "соответствию заданию (стиль — во вторую очередь).\n"
    "Ответь СТРОГО так: первая строка «ВЫБОР: N», где N — номер варианта (с 0); "
    "затем одна-две строки обоснования. Никакого кода в ответе."
)

_CHOICE_RE = re.compile(r"ВЫБОР\s*[:=]?\s*(\d+)", re.IGNORECASE)
_FALLBACK_RE = re.compile(r"\d+")


def parse_choice(reply: str, n: int) -> int:
    """Достаёт индекс выбранного варианта из ответа судьи, обрезая в [0, n-1].

    Сначала ищет строку «ВЫБОР: N», иначе — первое число в ответе; если ничего
    не нашлось или вышли за диапазон, возвращает 0 (первый вариант).
    """
    if n <= 1:
        return 0
    match = _CHOICE_RE.search(reply or "") or _FALLBACK_RE.search(reply or "")
    if not match:
        return 0
    idx = int(match.group(match.lastindex or 0))
    return idx if 0 <= idx < n else 0


def _format_candidates(candidates: list[str]) -> str:
    return "\n\n".join(
        f"### Вариант {i}\n```\n{c.strip()}\n```" for i, c in enumerate(candidates)
    )


def select_best(client: LLMClient, task: Task, candidates: list[str],
                context: str = "") -> tuple[int, str]:
    """Возвращает (индекс лучшего варианта, текст ответа судьи).

    При одном кандидате модель не дёргается. Индекс всегда валиден (обрезан
    в диапазон), так что результат можно сразу подавать в select_variant.
    """
    if len(candidates) <= 1:
        return 0, ""
    parts = [
        f"Пункт «{task.key} {task.title}»",
        f"Что требуется:\n{task.body}" if task.body else "",
        f"Контракты зависимостей:\n{context}" if context else "",
        f"Варианты реализации ({len(candidates)} шт.):\n{_format_candidates(candidates)}",
    ]
    reply = client.ask(JUDGE_SYSTEM, "\n\n".join(p for p in parts if p)).strip()
    return parse_choice(reply, len(candidates)), reply
