"""Архитектор: из краткого брифа большая модель делает ТЗ+ФС+TODO.

Результат — YAML в том же формате, что и ручной импорт (см. examples/), поэтому
он сразу кладётся в базу через importer.import_todo_data.
"""

from __future__ import annotations

import yaml

from ..llm import LLMClient
from .coder import strip_code_fences

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
    data = yaml.safe_load(strip_code_fences(raw))
    if not isinstance(data, dict) or "project" not in data or "tasks" not in data:
        raise ValueError(
            "Архитектор вернул не план Nanotasks (нет project/tasks):\n" + raw[:500]
        )
    return data


def run_architect(client: LLMClient, brief: str, language: str | None = None) -> dict:
    user = brief if not language else f"Целевой язык: {language}\n\nБриф:\n{brief}"
    raw = client.ask(ARCHITECT_SYSTEM, user)
    return parse_plan(raw)
