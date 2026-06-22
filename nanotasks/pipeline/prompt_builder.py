"""Генерация нано-промпта моделью-постановщиком (prompt_builder).

Берёт пункт TODO + контракты зависимостей (а при исправлении — ещё текущий код
и замечания) и формулирует ОДНО короткое самодостаточное задание для кодера.
"""

from __future__ import annotations

from ..llm import LLMClient
from ..models import Task

SYSTEM = (
    "Ты — постановщик задач для маленькой модели-кодера с крошечным контекстом. "
    "По описанию пункта и контрактам зависимостей составь ОДИН короткий, полностью "
    "самодостаточный промпт, по которому кодер напишет код, не видя остального проекта.\n"
    "Обязательно укажи: что создать; точные сигнатуры (имена, аргументы, типы, "
    "возвращаемое значение); формат входа/выхода; важные ограничения. Сигнатуры из "
    "контрактов зависимостей используй ДОСЛОВНО, ничего не выдумывай.\n"
    "Если дана текущая версия кода и замечания — потребуй ИСПРАВЛЕННЫЙ полный файл, "
    "устраняющий все замечания.\n"
    "Не пиши сам код и не добавляй пояснений — выведи только текст задания для кодера."
)


def build_nano_prompt(client: LLMClient, task: Task, context: str, language: str,
                      current_code: str | None = None,
                      feedback: list[str] | None = None) -> str:
    feedback = feedback or []
    parts = [
        f"Целевой язык: {language}",
        f"Тип артефакта: {task.type.value}",
    ]
    if task.file_path:
        parts.append(f"Файл: {task.file_path}")
    parts.append(f"Что нужно сделать (пункт TODO «{task.key} {task.title}»):\n{task.body}")
    if context:
        parts.append("Контракты зависимостей (используй их сигнатуры дословно):\n" + context)
    if current_code:
        parts.append("Текущая версия кода (её нужно исправить):\n```\n" + current_code + "\n```")
    if feedback:
        bullets = "\n".join(f"- {item}" for item in feedback)
        parts.append("Замечания, которые НУЖНО устранить:\n" + bullets)

    user = "\n\n".join(parts)
    return client.ask(SYSTEM, user).strip()
