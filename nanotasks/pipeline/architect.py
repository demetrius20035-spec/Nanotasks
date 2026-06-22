"""Архитектор: из краткого брифа большая модель делает ТЗ+ФС+TODO.

Результат — YAML в том же формате, что и ручной импорт (см. examples/), поэтому
он сразу кладётся в базу через importer.import_todo_data.
"""

from __future__ import annotations

from ..llm import LLMClient
from ..textutil import load_yaml_lenient

ARCHITECT_SYSTEM = (
    "Ты — системный архитектор. По краткому брифу составь полный план разработки и "
    "верни СТРОГО YAML (без markdown-ограждений) в формате импорта Nanotasks:\n"
    "project:\n"
    "  name: <имя>\n"
    "  language: <язык>\n"
    "  description: <одна строка>\n"
    "  spec: |\n"
    "    <ТЗ и ФС: цели, требования, архитектура, интерфейсы модулей>\n"
    "tasks:   # дерево пунктов: пункт → подпункт → подподпункт через children\n"
    "  - key: '1'\n"
    "    title: <название>\n"
    "    type: group|code|yaml|config|doc|test\n"
    "    file: <путь файла для листьев>\n"
    "    depends_on: [<ключи пунктов, чьи контракты нужны>]\n"
    "    body: <что именно сделать: сигнатуры, вход/выход, ограничения>\n"
    "    children: [...]\n"
    "Декомпозируй на МЕЛКИЕ самодостаточные пункты (один файл или одна функция — "
    "один лист). Обязательно проставляй depends_on там, где пункту нужны контракты "
    "других пунктов. Ничего вне YAML не пиши."
)


def parse_plan(raw: str) -> dict:
    data = load_yaml_lenient(raw)
    if "project" not in data or "tasks" not in data:
        raise ValueError(
            "Архитектор вернул не план Nanotasks (нет project/tasks):\n" + raw[:500]
        )
    return data


def run_architect(client: LLMClient, brief: str, language: str | None = None,
                  retries: int = 1) -> dict:
    user = brief if not language else f"Целевой язык: {language}\n\nБриф:\n{brief}"
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            return parse_plan(client.ask(ARCHITECT_SYSTEM, user))
        except ValueError as exc:
            last = exc
    raise last  # type: ignore[misc]
